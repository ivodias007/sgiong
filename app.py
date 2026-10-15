# app.py
# SGIONGs - Plataforma de filtragem de ONGs/OSCs (Gaza)
# Flask + SQLite + Bootstrap 5

import json
import math
import os
import uuid
import secrets
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session, abort, Response, jsonify, make_response
from werkzeug.security import check_password_hash, generate_password_hash
import perfis
import auditoria
import relatorios
import seguranca
import backup
import duplicados
import contas_iniciais
import chatbot
import re
import sobreposicoes
import importacao_web
import login_guard
import importar_dados as importador_cli
from werkzeug.utils import secure_filename
from markupsafe import Markup, escape

from database import get_connection, init_db
from tagging import (detetar_distritos, detetar_areas, detetar_ramificacoes, PROVINCIAS,
                      AREAS_TEMATICAS, ESTRUTURA_AREAS_TEMATICAS, DISTRITOS_POR_PROVINCIA,
                      icone_area)
from config import (ADMIN_USERNAME, ADMIN_PASSWORD_HASH, SUPER_ADMIN_USERNAME, ADMIN_EMAIL, SUPER_ADMIN_EMAIL,
                     SUPER_ADMIN_PASSWORD_HASH, USANDO_SENHAS_POR_DEFEITO,
                     DURACAO_SESSAO_MINUTOS, PRODUCAO, EXIGIR_2FA_ADMIN, PERFIS_2FA_OBRIGATORIO, LEGADO_ADMIN_ACTIVO, LEGADO_SUPERADMIN_ACTIVO,
                     BOOTSTRAP_EMAIL, BOOTSTRAP_PASSWORD)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 12 * 1024 * 1024  # 12 MB — cobre matrizes Excel e logótipos de ONGs

# A secret_key assina as sessões de login. Em vez de um texto fixo no código
# (que seria igual em todas as instalações do SGIONGs, e portanto previsível),
# geramos uma chave aleatória única na primeira vez que a app corre, e
# guardamo-la num ficheiro local para se manter estável entre reinícios.
# Em produção pode (e deve) vir da variável SGIONGS_SECRET_KEY.
if os.environ.get('SGIONGS_SECRET_KEY'):
    app.secret_key = os.environ['SGIONGS_SECRET_KEY']
else:
    from database import DATA_DIR as _DATA_DIR
    os.makedirs(_DATA_DIR, exist_ok=True)
    _CAMINHO_CHAVE = os.path.join(_DATA_DIR, '.chave_secreta')
    if not os.path.exists(_CAMINHO_CHAVE):
        with open(_CAMINHO_CHAVE, 'w') as f:
            f.write(secrets.token_hex(32))
        try:
            os.chmod(_CAMINHO_CHAVE, 0o600)
        except OSError:
            pass
    with open(_CAMINHO_CHAVE) as f:
        app.secret_key = f.read().strip()

# Atrás do proxy do alojamento (Render, nginx…) o IP real vem em X-Forwarded-For;
# sem isto todos os utilizadores pareceriam ter o mesmo IP e bloqueavam-se uns aos outros.
if PRODUCAO:
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# ─── ENDURECIMENTO DE SEGURANÇA DA SESSÃO ─────────────────────────────────────
app.config['SESSION_COOKIE_HTTPONLY'] = True      # cookie de sessão inacessível a JavaScript
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'     # protecção base contra CSRF cross-site
app.config['SESSION_COOKIE_SECURE'] = PRODUCAO    # só enviar o cookie por HTTPS em produção
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=DURACAO_SESSAO_MINUTOS)


@app.before_request
def _sessao_permanente_com_expiracao():
    session.permanent = True


@app.after_request
def _cabecalhos_de_seguranca(resposta):
    """Cabeçalhos HTTP que reduzem a superfície de ataque (clickjacking,
    MIME-sniffing, referrer leakage, etc.) sem afectar o funcionamento normal
    da aplicação."""
    resposta.headers['X-Content-Type-Options'] = 'nosniff'
    resposta.headers['X-Frame-Options'] = 'DENY'
    resposta.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    if PRODUCAO:
        resposta.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return resposta


if PRODUCAO:
    @app.before_request
    def _forcar_https():
        if request.headers.get('X-Forwarded-Proto', request.scheme) != 'https':
            return redirect(request.url.replace('http://', 'https://', 1), code=301)


# ─── PROTEÇÃO CSRF ────────────────────────────────────────────────────────────
# Todos os formulários que alteram dados (POST) têm de incluir um campo
# escondido 'csrf_token' com o valor gerado para a sessão actual. Sem isto,
# um site malicioso poderia induzir o browser de um Admin com sessão iniciada
# a submeter pedidos sem o seu conhecimento.
@app.context_processor
def injetar_csrf_token():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
    return {'csrf_token': session['csrf_token']}


@app.before_request
def _validar_csrf():
    if request.method == 'POST':
        token_sessao = session.get('csrf_token')
        token_formulario = request.form.get('csrf_token')
        if not token_sessao or not token_formulario or not secrets.compare_digest(token_sessao, token_formulario):
            abort(400, description='Pedido inválido ou sessão expirada. Actualize a página e tente novamente.')

POR_PAGINA = 12

# ─── EMBLEMA/AVATAR AUTOMÁTICO DAS ONGs ───────────────────────────────────────
# Não usamos logótipos oficiais reais (a maioria das ONGs locais não tem
# nenhum disponível publicamente, e os das ONGs internacionais são marcas
# registadas que não podemos reproduzir sem autorização). Em vez disso,
# geramos um emblema simples e consistente: um círculo colorido com as
# iniciais do nome — a cor é sempre a mesma para a mesma ONG.
_CORES_AVATAR = [
    '#0d6efd', '#6610f2', '#6f42c1', '#d63384', '#dc3545', '#fd7e14',
    '#198754', '#20c997', '#0dcaf0', '#495057', '#8B5E34', '#146c43',
]


@app.template_filter('iniciais')
def filtro_iniciais(nome):
    if not nome:
        return '?'
    palavras = [p for p in nome.strip().split()]
    if not palavras:
        return '?'
    if len(palavras) == 1:
        return palavras[0][:2].upper()
    return (palavras[0][0] + palavras[1][0]).upper()


@app.template_filter('cor_avatar')
def filtro_cor_avatar(nome):
    if not nome:
        return _CORES_AVATAR[0]
    indice = sum(ord(c) for c in nome) % len(_CORES_AVATAR)
    return _CORES_AVATAR[indice]


@app.template_filter('icone_area')
def filtro_icone_area(nome_area):
    return icone_area(nome_area)


@app.context_processor
def injetar_distritos_por_provincia():
    """Disponibiliza o mapa de distritos-por-província em todos os templates,
    para os selects de distrito serem preenchidos dinamicamente em função da
    província escolhida (registo e filtros), sem pedidos extra ao servidor."""
    return {'distritos_por_provincia_json': {p: sorted(ds.keys()) for p, ds in DISTRITOS_POR_PROVINCIA.items()}}



# ─── FUNÇÕES DE SESSÃO ────────────────────────────────────────────────────────
def nivel_sessao():
    """Devolve o nível do utilizador autenticado: 'superadmin', 'admin' ou None."""
    return session.get('nivel')

def e_admin():
    return nivel_sessao() in ('admin', 'superadmin')

def e_super_admin():
    return nivel_sessao() == 'superadmin'


def perfil_sessao():
    """Perfil granular da sessão actual (ver perfis.py). None se não autenticado."""
    return session.get('perfil')


def provincia_sessao():
    """Devolve a província a que a sessão está limitada, ou None se não há
    limitação (super_admin, admin, gestor_nacional e as contas legadas veem
    o país inteiro; só gestor_provincial fica restrito)."""
    if perfil_sessao() == 'gestor_provincial':
        return session.get('provincia')
    return None


# ─── DECORATORS ───────────────────────────────────────────────────────────────
def _auditar_acesso_negado(requisito):
    try:
        conn = get_connection()
        auditoria.registar(conn, 'acesso_negado',
                            f'{session.get("utilizador")} ({session.get("perfil")}) tentou aceder a {request.method} {request.path} sem {requisito}',
                            utilizador=session.get('utilizador'), ip=request.remote_addr)
        conn.commit()
        conn.close()
    except Exception:
        pass


def login_obrigatorio(f):
    """Permite acesso a qualquer utilizador autenticado (admin ou superadmin)."""
    @wraps(f)
    def decorada(*args, **kwargs):
        if not e_admin():
            flash('Precisa de iniciar sessão para fazer essa ação.', 'warning')
            destino = request.path if request.method == 'GET' else (request.referrer or url_for('inicio'))
            return redirect(url_for('login', next=destino))
        return f(*args, **kwargs)
    return decorada


def super_admin_obrigatorio(f):
    """Permite acesso apenas ao Super Administrador."""
    @wraps(f)
    def decorada(*args, **kwargs):
        if not e_super_admin():
            _auditar_acesso_negado('Super Administrador')
            flash('Esta ação requer permissão de Super Administrador.', 'danger')
            return redirect(url_for('inicio'))
        return f(*args, **kwargs)
    return decorada


def requer_permissao(accao):
    """Decorador granular baseado no perfil real (ver perfis.PERMISSOES).
    Complementa login_obrigatorio/super_admin_obrigatorio — não os substitui,
    para as rotas ainda não migradas continuarem a funcionar exactamente
    como antes."""
    def decorator(f):
        @wraps(f)
        def decorada(*args, **kwargs):
            if not e_admin():
                flash('Precisa de iniciar sessão para fazer essa ação.', 'warning')
                return redirect(url_for('login', next=request.path))
            perfil = perfil_sessao() or ('super_admin' if e_super_admin() else 'admin')
            if not perfis.tem_permissao(perfil, accao):
                _auditar_acesso_negado(f'permissão "{accao}"')
                flash('O seu perfil não tem permissão para esta ação.', 'danger')
                return redirect(url_for('inicio'))
            return f(*args, **kwargs)
        return decorada
    return decorator


# ─── ROTAS DE AUTENTICAÇÃO ────────────────────────────────────────────────────
def _destino_seguro(destino, vazio=False):
    """Só aceita caminhos internos ('/algo'); rejeita '//outro-site', 'http://…' e '\\'
    (open redirect)."""
    if destino and destino.startswith('/') and not destino.startswith('//') and '\\' not in destino \
            and '\n' not in destino and '\r' not in destino:
        return destino
    return '' if vazio else url_for('inicio')


def _sem_cache(html):
    r = make_response(html)
    r.headers['Cache-Control'] = 'no-store'
    return r


def _marcar_exigencias_sessao(linha):
    """Define o que a conta tem de fazer antes de usar o sistema: mudar a senha
    temporária e/ou configurar o 2FA (obrigatório nos perfis administrativos)."""
    session['deve_mudar_senha'] = bool(linha['deve_mudar_senha'])
    session['deve_configurar_2fa'] = bool(EXIGIR_2FA_ADMIN and linha['perfil'] in PERFIS_2FA_OBRIGATORIO
                                          and not linha['totp_ativo'])


@app.route('/login', methods=['GET', 'POST'])
def login():
    if e_admin():
        return redirect(url_for('inicio'))
    if request.method == 'POST':
        ip = request.remote_addr
        utilizador = request.form.get('utilizador', '').strip()
        senha = request.form.get('senha', '')

        conn = get_connection()
        if login_guard.bloqueado(conn, ip, utilizador):
            conn.close()
            flash('Demasiadas tentativas falhadas. Aguarde 15 minutos ou peça a um administrador para repor o acesso.', 'danger')
            return render_template('login.html', next=request.args.get('next', '')), 429
        linha = conn.execute(
            'SELECT * FROM utilizadores WHERE (username = ? OR lower(email) = lower(?)) AND activo = 1',
            (utilizador, utilizador)
        ).fetchone()

        autenticado = False
        if linha and check_password_hash(linha['password_hash'], senha):
            if linha['totp_ativo']:
                # Password correcta, mas falta o código do autenticador —
                # a sessão só fica completa depois de /login/2fa.
                conn.close()
                session.clear()
                session['pendente_2fa_utilizador_id'] = linha['id']
                session['pendente_2fa_conta'] = utilizador
                return redirect(url_for('login_2fa', next=_destino_seguro(request.args.get('next', ''), vazio=True)))
            # Conta nova, baseada na tabela utilizadores — perfil granular.
            session.clear()  # evita fixação de sessão
            session['perfil'] = linha['perfil']
            session['nivel'] = perfis.nivel_legado_para_perfil(linha['perfil'])
            session['utilizador_id'] = linha['id']
            session['provincia'] = linha['provincia']
            session['nome_completo'] = linha['nome_completo']
            _marcar_exigencias_sessao(linha)
            utilizador = linha['username']  # nome canónico (o login pode ter sido feito com o e-mail)
            conn.execute('UPDATE utilizadores SET ultimo_login = datetime("now") WHERE id = ?', (linha['id'],))
            conn.commit()
            flash(f'Sessão iniciada como {perfis.ROTULOS_PERFIS.get(linha["perfil"], linha["perfil"])}.', 'success')
            autenticado = True
        elif LEGADO_SUPERADMIN_ACTIVO and utilizador.lower() in (SUPER_ADMIN_USERNAME.lower(), SUPER_ADMIN_EMAIL or '\0') and check_password_hash(SUPER_ADMIN_PASSWORD_HASH, senha):
            # Conta legada (variável de ambiente) — mantida por compatibilidade.
            session.clear()
            session['perfil'] = 'super_admin'
            session['nivel'] = 'superadmin'
            session['utilizador_id'] = None
            session['provincia'] = None
            flash('Sessão de Super Administrador iniciada.', 'success')
            autenticado = True
        elif LEGADO_ADMIN_ACTIVO and utilizador.lower() in (ADMIN_USERNAME.lower(), ADMIN_EMAIL or '\0') and check_password_hash(ADMIN_PASSWORD_HASH, senha):
            session.clear()
            session['perfil'] = 'admin'
            session['nivel'] = 'admin'
            session['utilizador_id'] = None
            session['provincia'] = None
            flash('Sessão de Administrador iniciada.', 'success')
            autenticado = True

        conn.close()

        if not autenticado:
            conn2 = get_connection()
            login_guard.registar_falha(conn2, ip, utilizador)
            auditoria.registar(conn2, 'login_falhado', f'Tentativa de login falhada para o utilizador "{utilizador}"',
                                utilizador=utilizador, ip=ip)
            conn2.commit()
            conn2.close()
            flash('Utilizador ou senha incorretos.', 'danger')
            return render_template('login.html', next=request.args.get('next', ''))

        session['utilizador'] = utilizador
        conn3 = get_connection()
        login_guard.limpar_conta(conn3, utilizador)
        auditoria.registar(conn3, 'login_sucesso', f'{utilizador} iniciou sessão', utilizador=utilizador, ip=ip)
        conn3.commit()
        conn3.close()
        return redirect(_destino_seguro(request.args.get('next') or request.form.get('next')))
    return render_template('login.html', next=request.args.get('next', ''))


@app.route('/login/2fa', methods=['GET', 'POST'])
def login_2fa():
    utilizador_id = session.get('pendente_2fa_utilizador_id')
    if not utilizador_id:
        return redirect(url_for('login'))

    if request.method == 'POST':
        ip = request.remote_addr
        codigo = request.form.get('codigo', '').strip()
        conta_2fa = session.get('pendente_2fa_conta') or str(utilizador_id)
        conn = get_connection()
        if login_guard.bloqueado(conn, ip, conta_2fa):
            conn.close()
            session.pop('pendente_2fa_utilizador_id', None)
            flash('Demasiadas tentativas falhadas. Aguarde 15 minutos ou peça a um administrador para repor o acesso.', 'danger')
            return redirect(url_for('login'))
        linha = conn.execute('SELECT * FROM utilizadores WHERE id = ? AND activo = 1', (utilizador_id,)).fetchone()

        passo = seguranca.passo_totp_valido(linha['totp_secret'], codigo, linha['totp_ultimo_passo']) if linha else None
        usou_recuperacao = False
        if linha and passo is None and seguranca.consumir_codigo_recuperacao(conn, linha['id'], codigo):
            usou_recuperacao = True
        if not linha or (passo is None and not usou_recuperacao):
            login_guard.registar_falha(conn, ip, conta_2fa)
            auditoria.registar(conn, 'login_falhado', f'Código 2FA inválido para "{conta_2fa}"', utilizador=conta_2fa, ip=ip)
            conn.commit()
            conn.close()
            flash('Código inválido ou já usado. Tente novamente.', 'danger')
            return render_template('login_2fa.html', next=request.args.get('next', ''))
        if passo is not None:
            conn.execute('UPDATE utilizadores SET totp_ultimo_passo = ? WHERE id = ?', (passo, linha['id']))
        if usou_recuperacao:
            restantes = seguranca.codigos_restantes(conn, linha['id'])
            auditoria.registar(conn, 'login_2fa_recuperacao',
                                f'{linha["username"]} entrou com um código de recuperação do 2FA ({restantes} restantes)',
                                utilizador=linha['username'], ip=ip)
            alertas.alertar('2fa-rec:' + linha['username'], f'Código de recuperação do 2FA usado por {linha["username"]}')

        login_guard.limpar_conta(conn, conta_2fa)
        session.clear()
        session['perfil'] = linha['perfil']
        session['nivel'] = perfis.nivel_legado_para_perfil(linha['perfil'])
        session['utilizador_id'] = linha['id']
        session['provincia'] = linha['provincia']
        session['nome_completo'] = linha['nome_completo']
        _marcar_exigencias_sessao(linha)
        session['utilizador'] = linha['username']
        conn.execute('UPDATE utilizadores SET ultimo_login = datetime("now") WHERE id = ?', (linha['id'],))
        auditoria.registar(conn, 'login_sucesso', f'{linha["username"]} iniciou sessão (com 2FA)',
                            utilizador=linha['username'], ip=ip)
        conn.commit()
        conn.close()
        flash(f'Sessão iniciada como {perfis.ROTULOS_PERFIS.get(linha["perfil"], linha["perfil"])}.', 'success')
        return redirect(_destino_seguro(request.args.get('next') or request.form.get('next')))

    return render_template('login_2fa.html', next=request.args.get('next', ''))


@app.route('/logout')
def logout():
    session.clear()
    flash('Sessão terminada.', 'info')
    return redirect(url_for('inicio'))


_BD_PRONTAS = set()


@app.before_request
def garantir_bd():
    # A inicialização/migração corre uma vez por processo e base de dados
    # (antes corria em todos os pedidos, o que era lento e desnecessário).
    from database import DB_PATH as _db
    if _db not in _BD_PRONTAS:
        init_db()
        _garantir_super_admin_inicial()
        try:
            import noticias_iniciais
            _c = get_connection()
            noticias_iniciais.completar_imagens(_c)
            _c.close()
        except Exception as _e:  # noqa: BLE001 — nunca impedir o arranque por causa de uma imagem
            app.logger.warning('completar_imagens: %r', _e)
        _BD_PRONTAS.add(_db)


@app.before_request
def _validar_sessao_activa():
    """Uma conta desactivada (ou despromovida/mudada de província) perde o acesso de imediato,
    sem esperar que a sessão expire: o estado é relido da base em cada pedido."""
    uid = session.get('utilizador_id')
    if not uid or request.endpoint in ('static', None):
        return None
    conn = get_connection()
    linha = conn.execute('SELECT activo, perfil, provincia FROM utilizadores WHERE id = ?', (uid,)).fetchone()
    conn.close()
    if not linha or not linha['activo']:
        session.clear()
        flash('A sua sessão foi terminada: a conta já não está activa.', 'warning')
        return redirect(url_for('login'))
    if linha['perfil'] != session.get('perfil') or linha['provincia'] != session.get('provincia'):
        session['perfil'] = linha['perfil']
        session['nivel'] = perfis.nivel_legado_para_perfil(linha['perfil'])
        session['provincia'] = linha['provincia']
    return None


@app.before_request
def _obrigar_mudar_senha():
    """Exigências pendentes da conta: 1.º mudar a senha temporária; 2.º configurar o 2FA
    (administradores). Até as cumprir só acede às páginas necessárias para isso."""
    if request.endpoint in ('static', 'logout', 'login', 'login_2fa', None):
        return None
    if session.get('deve_mudar_senha'):
        if request.endpoint in ('conta', 'alterar_propria_senha'):
            return None
        flash('Por segurança, defina uma nova palavra-passe antes de continuar.', 'warning')
        return redirect(url_for('conta'))
    if session.get('deve_configurar_2fa'):
        if request.endpoint in ('conta', 'configurar_2fa', 'qrcode_2fa', 'activar_2fa'):
            return None
        flash('Os administradores têm de activar a verificação em duas etapas (2FA) antes de continuar.', 'warning')
        return redirect(url_for('configurar_2fa'))


@app.context_processor
def injetar_total_pendentes():
    """Disponibiliza total_pendentes, pode_aprovar e pode_gerir_utilizadores
    a todos os templates, com base no perfil real da sessão (ver perfis.py),
    respeitando o âmbito de província do Gestor Provincial."""
    perfil = perfil_sessao() or ('super_admin' if e_super_admin() else ('admin' if e_admin() else None))
    contexto = {
        'usando_senhas_por_defeito': USANDO_SENHAS_POR_DEFEITO if e_admin() else False,
        'recuperacao_email_activa': emails.disponivel(),
        'pode_aprovar': bool(perfil and perfis.tem_permissao(perfil, 'aprovar')),
        'pode_gerir_utilizadores': bool(perfil and perfis.tem_permissao(perfil, 'gerir_utilizadores')),
        'pode_eliminar': bool(perfil and perfis.tem_permissao(perfil, 'eliminar')),
        'pode_gerir_noticias': bool(perfil and perfis.tem_permissao(perfil, 'gerir_noticias')),
        'pode_ver_auditoria': bool(perfil and perfis.tem_permissao(perfil, 'ver_auditoria')),
        'rotulo_perfil_sessao': perfis.ROTULOS_PERFIS.get(perfil, 'Administrador') if perfil else None,
    }
    escopo_provincia = provincia_sessao()

    if contexto['pode_aprovar']:
        conn = get_connection()
        if escopo_provincia:
            total_registos = conn.execute(
                "SELECT COUNT(*) c FROM ongs WHERE aprovacao = 'Pendente' AND provincia = ?", (escopo_provincia,)
            ).fetchone()['c']
            total_edicoes = conn.execute('''
                SELECT COUNT(*) c FROM alteracoes_pendentes ap
                JOIN ongs o ON o.id = ap.ong_id
                WHERE ap.estado = 'Pendente' AND o.provincia = ?
            ''', (escopo_provincia,)).fetchone()['c']
        else:
            total_registos = conn.execute("SELECT COUNT(*) c FROM ongs WHERE aprovacao = 'Pendente'").fetchone()['c']
            total_edicoes = conn.execute("SELECT COUNT(*) c FROM alteracoes_pendentes WHERE estado = 'Pendente'").fetchone()['c']
        conn.close()
        contexto.update({'total_pendentes': total_registos + total_edicoes,
                          'total_registos_pendentes': total_registos,
                          'total_edicoes_pendentes': total_edicoes})
    else:
        contexto['total_pendentes'] = 0

    if contexto['pode_ver_auditoria']:
        conn = get_connection()
        contexto['total_sobreposicoes'] = sobreposicoes.contar_sobreposicoes(conn, provincia=escopo_provincia)
        grupos_preview, _ = sobreposicoes.procurar_sobreposicoes(conn, provincia=escopo_provincia, limite=5)
        conn.close()
        contexto['sobreposicoes_preview'] = grupos_preview
    else:
        contexto['total_sobreposicoes'] = 0
        contexto['sobreposicoes_preview'] = []

    return contexto


def obter_ou_criar_id(conn, tabela, nome):
    cur = conn.execute(f'SELECT id FROM {tabela} WHERE nome = ?', (nome,))
    linha = cur.fetchone()
    if linha:
        return linha['id']
    cur = conn.execute(f'INSERT INTO {tabela} (nome) VALUES (?)', (nome,))
    return cur.lastrowid


def obter_ou_criar_ramificacao_id(conn, nome, area_id):
    cur = conn.execute('SELECT id FROM ramificacoes WHERE nome = ?', (nome,))
    linha = cur.fetchone()
    if linha:
        return linha['id']
    cur = conn.execute('INSERT INTO ramificacoes (nome, area_id) VALUES (?, ?)', (nome, area_id))
    return cur.lastrowid


SUB_PARA_AREA = {sub: area for area, subs in ESTRUTURA_AREAS_TEMATICAS.items() for sub in subs}


CAMPOS_EDITAVEIS = [
    'nome', 'sigla', 'natureza', 'origem', 'ano_entrada_pais', 'logo_url', 'provincia',
    'area_intervencao', 'programas', 'projetos_em_curso', 'fonte_financiamento',
    'distritos_texto', 'perfil_grupo_alvo', 'pessoa_contacto', 'telefone', 'email',
    'coordenada_x', 'coordenada_y', 'estado',
]

# Rótulos amigáveis para o ecrã de comparação (antes/depois) que o Super
# Administrador vê ao rever uma alteração proposta por um Administrador.
ROTULOS_CAMPOS = {
    'nome': 'Nome', 'sigla': 'Sigla', 'natureza': 'Natureza', 'origem': 'Origem',
    'ano_entrada_pais': 'Ano de entrada no país', 'logo_url': 'Logótipo',
    'provincia': 'Província principal', 'provincias': 'Província(s)',
    'area_intervencao': 'Área/s Temática/s', 'programas': 'Programas',
    'projetos_em_curso': 'Projectos em Curso', 'fonte_financiamento': 'Fonte de Financiamento',
    'distritos_texto': 'Distrito(s)', 'perfil_grupo_alvo': 'Perfil do Grupo Alvo',
    'pessoa_contacto': 'Ponto Focal', 'telefone': 'Telefone', 'email': 'E-mail',
    'coordenada_x': 'Coordenada X', 'coordenada_y': 'Coordenada Y', 'estado': 'Estado',
}


import logging
import shutil
import alertas
import emails
from logging.handlers import RotatingFileHandler


def _configurar_logs():
    from database import DATA_DIR as _d
    try:
        os.makedirs(os.path.join(_d, 'logs'), exist_ok=True)
        h = RotatingFileHandler(os.path.join(_d, 'logs', 'erros.log'), maxBytes=1_000_000, backupCount=5, encoding='utf-8')
        h.setLevel(logging.WARNING)
        h.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        app.logger.addHandler(h)
    except OSError:
        pass


_configurar_logs()


def _uploads_no_disco_persistente():
    """Se SGIONGS_DATA_DIR está definido, static/uploads passa a ser um atalho
    para DATA_DIR/uploads, para logótipos e imagens de notícias sobreviverem
    a reinícios e novas publicações."""
    if not os.environ.get('SGIONGS_DATA_DIR'):
        return
    from database import DATA_DIR as _d
    destino = os.path.join(_d, 'uploads')
    atalho = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads')
    try:
        os.makedirs(destino, exist_ok=True)
        if os.path.islink(atalho):
            return
        if os.path.isdir(atalho):
            for nome in os.listdir(atalho):
                shutil.move(os.path.join(atalho, nome), os.path.join(destino, nome))
            os.rmdir(atalho)
        os.symlink(destino, atalho)
    except OSError as e:
        app.logger.error('Não consegui ligar static/uploads ao disco persistente: %s', e)


_uploads_no_disco_persistente()


def _pagina_erro(codigo, titulo, mensagem):
    return render_template('erro.html', codigo=codigo, titulo=titulo, mensagem=mensagem), codigo


@app.errorhandler(400)
def _erro_400(e):
    return _pagina_erro(400, 'Pedido inválido', getattr(e, 'description', None) or
                        'O pedido não pôde ser processado. Actualize a página e tente novamente.')


@app.errorhandler(403)
def _erro_403(e):
    return _pagina_erro(403, 'Sem autorização', 'Não tem permissão para aceder a esta página.')


@app.errorhandler(404)
def _erro_404(e):
    return _pagina_erro(404, 'Página não encontrada', 'O endereço não existe ou o registo foi removido.')


@app.errorhandler(429)
def _erro_429(e):
    return _pagina_erro(429, 'Demasiados pedidos', 'Aguarde um pouco e tente novamente.')


@app.errorhandler(500)
def _erro_500(e):
    app.logger.error('Erro 500 em %s %s: %r', request.method, request.path, e, exc_info=getattr(e, 'original_exception', None))
    alertas.alertar(f'500:{request.path}', f'Erro interno em {request.method} {request.path}: {e!r}')
    try:
        conn = get_connection()
        auditoria.registar(conn, 'erro_sistema', f'Erro interno em {request.method} {request.path}',
                            utilizador=session.get('utilizador'), ip=request.remote_addr)
        conn.commit()
        conn.close()
    except Exception:
        pass
    aviso = ' A equipa técnica foi avisada.' if alertas.alertas_activos() else ''
    return _pagina_erro(500, 'Algo correu mal',
                        'Ocorreu um erro inesperado. Os dados não foram perdidos e o erro ficou registado.' + aviso +
                        ' Tente novamente dentro de instantes.')


@app.route('/saude')
def saude():
    """Verificação de saúde para monitoria externa (UptimeRobot, Render, etc.):
    200 se a base de dados responde e o último backup é recente; 503 caso contrário.
    Não expõe dados sensíveis."""
    estado = {'base_dados': False, 'ongs': None, 'ultimo_backup_horas': None, 'backup_recente': None}
    try:
        conn = get_connection()
        estado['ongs'] = conn.execute('SELECT COUNT(*) FROM ongs').fetchone()[0]
        estado['base_dados'] = conn.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
        conn.close()
    except Exception:
        pass
    idade = backup.idade_ultimo_backup_horas()
    estado['ultimo_backup_horas'] = None if idade is None else round(idade, 1)
    estado['backup_recente'] = idade is not None and idade < 36
    ok = estado['base_dados'] and (estado['backup_recente'] or not PRODUCAO)
    estado['estado'] = 'ok' if ok else 'falha'
    if not ok:
        alertas.alertar('saude', f'Verificação de saúde falhou: {estado}')
    return jsonify(estado), (200 if ok else 503)


@app.errorhandler(413)
def _ficheiro_demasiado_grande(e):
    flash('O ficheiro enviado é demasiado grande (máximo 12 MB no total do pedido; logótipos até 2 MB).', 'danger')
    return redirect(request.referrer or url_for('inicio'))


PASTA_LOGOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads', 'logos')
EXTENSOES_LOGO_PERMITIDAS = {'.png', '.jpg', '.jpeg', '.svg', '.webp'}
TAMANHO_MAXIMO_LOGO = 2 * 1024 * 1024  # 2 MB


def processar_upload_logo(arquivo, logo_atual=None):
    """Valida e grava o ficheiro de logótipo enviado, devolvendo
    (logo_url, erro). Se não vier nenhum ficheiro novo, mantém o logótipo
    actual sem alterações (útil ao editar sem trocar a imagem)."""
    if not arquivo or not arquivo.filename:
        return logo_atual, None

    nome_seguro = secure_filename(arquivo.filename)
    extensao = os.path.splitext(nome_seguro)[1].lower()
    if extensao not in EXTENSOES_LOGO_PERMITIDAS:
        return logo_atual, 'Formato de imagem não suportado — use PNG, JPG, SVG ou WEBP.'

    arquivo.stream.seek(0, os.SEEK_END)
    tamanho = arquivo.stream.tell()
    arquivo.stream.seek(0)
    if tamanho > TAMANHO_MAXIMO_LOGO:
        return logo_atual, 'O logótipo não pode ultrapassar 2 MB.'
    if tamanho == 0:
        return logo_atual, None  # campo de ficheiro veio vazio, não é bem um envio

    os.makedirs(PASTA_LOGOS, exist_ok=True)
    nome_final = f'{uuid.uuid4().hex}{extensao}'
    arquivo.save(os.path.join(PASTA_LOGOS, nome_final))
    return url_for('static', filename=f'uploads/logos/{nome_final}'), None


def _url_segura(url):
    """Só aceita http(s) — recusa esquemas como javascript: que poderiam ser
    usados para injectar código através do campo de logótipo."""
    url = (url or '').strip()
    if not url:
        return None
    if not (url.startswith('http://') or url.startswith('https://')):
        return None
    return url


def _prov_unica(dados):
    """Com várias províncias seleccionadas, os distritos são detectados em
    todo o universo (os nomes já foram validados contra as províncias)."""
    provs = dados.get('provincias') or []
    return provs[0] if len(provs) == 1 else None


def _distritos_da_ong(conn, ong_id):
    return [r['nome'] for r in conn.execute(
        'SELECT d.nome FROM ong_distritos od JOIN distritos d ON d.id=od.distrito_id WHERE od.ong_id=? ORDER BY d.nome',
        (ong_id,)).fetchall()]


def _dados_formulario_ong(form):
    """Lê e normaliza os campos do formulário de registo/edição de ONG."""
    provincias = [p for p in form.getlist('provincias') if p in PROVINCIAS]
    # Distritos escolhidos na caixa de selecção: só são aceites os que
    # pertencem às províncias seleccionadas (valida no servidor).
    validos = {d for p in provincias for d in DISTRITOS_POR_PROVINCIA.get(p, {})}
    distritos_lista = []
    for d in form.getlist('distritos'):
        if d in validos and d not in distritos_lista:
            distritos_lista.append(d)
    ano_entrada_pais = form.get('ano_entrada_pais') or ''
    return {
        'nome': form.get('nome', '').strip(),
        'sigla': form.get('sigla', '').strip() or None,
        'natureza': form.get('natureza') or None,
        'origem': form.get('origem') or None,
        'ano_entrada_pais': int(ano_entrada_pais) if ano_entrada_pais.isdigit() else None,
        'logo_url': _url_segura(form.get('logo_url')),
        'provincia': provincias[0] if provincias else None,
        'provincias': provincias,
        'area_intervencao': form.get('area_intervencao') or None,
        'programas': form.get('programas') or None,
        'projetos_em_curso': form.get('projetos_em_curso') or None,
        'fonte_financiamento': form.get('fonte_financiamento') or None,
        'distritos_texto': ', '.join(distritos_lista) or None,
        'distritos_lista': distritos_lista,
        'perfil_grupo_alvo': form.get('perfil_grupo_alvo') or None,
        'pessoa_contacto': form.get('pessoa_contacto') or None,
        'telefone': form.get('telefone') or None,
        'email': form.get('email') or None,
        'coordenada_x': form.get('coordenada_x') or None,
        'coordenada_y': form.get('coordenada_y') or None,
        'estado': form.get('estado') or 'Ativo',
    }


def _aplicar_alteracoes_ong(conn, ong_id, dados):
    """Grava os novos valores na ONG e sincroniza as tabelas relacionadas
    (distritos, áreas, províncias, naturezas). Usado tanto quando um Super
    Admin edita directamente, como quando aprova uma alteração pendente."""
    conn.execute(f'''
        UPDATE ongs SET {", ".join(f"{c}=?" for c in CAMPOS_EDITAVEIS)}
        WHERE id=?
    ''', tuple(dados.get(c) for c in CAMPOS_EDITAVEIS) + (ong_id,))
    sincronizar_tags(conn, ong_id, dados.get('distritos_texto'), dados.get('area_intervencao'), _prov_unica(dados), dados.get('distritos_lista'))
    sincronizar_provincias(conn, ong_id, dados.get('provincias') or [])
    sincronizar_naturezas(conn, ong_id, dados.get('natureza'))


def _dados_atuais_da_ong(conn, ong):
    """Devolve um dicionário com o estado actual da ONG, no mesmo formato que
    _dados_formulario_ong, para poder comparar antes/depois."""
    dados = {c: ong[c] for c in CAMPOS_EDITAVEIS}
    dados['provincias'] = obter_provincias_da_ong(conn, ong['id']) or ([ong['provincia']] if ong['provincia'] else [])
    return dados


def _diferencas(antigos, novos):
    """Lista de dicionários só para os campos que realmente mudaram — para
    mostrar um resumo claro ao Super Admin (antes -> depois)."""
    diffs = []
    for campo in list(CAMPOS_EDITAVEIS) + ['provincias']:
        antigo = antigos.get(campo)
        novo = novos.get(campo)
        if campo == 'provincias':
            mudou = sorted(antigo or []) != sorted(novo or [])
            antigo_repr = ', '.join(sorted(antigo)) if antigo else '—'
            novo_repr = ', '.join(sorted(novo)) if novo else '—'
        else:
            mudou = antigo != novo
            antigo_repr = antigo if antigo not in (None, '') else '—'
            novo_repr = novo if novo not in (None, '') else '—'
        if mudou:
            diffs.append({'campo': campo, 'rotulo': ROTULOS_CAMPOS.get(campo, campo),
                          'antigo': antigo_repr, 'novo': novo_repr})
    return diffs


def sincronizar_tags(conn, ong_id, distritos_texto, area_texto, provincia=None, distritos_lista=None):
    conn.execute('DELETE FROM ong_distritos WHERE ong_id = ?', (ong_id,))
    conn.execute('DELETE FROM ong_areas WHERE ong_id = ?', (ong_id,))
    conn.execute('DELETE FROM ong_ramificacoes WHERE ong_id = ?', (ong_id,))
    # Distritos escolhidos na caixa de selecção são gravados tal e qual
    # (sem deteção por texto, que poderia acrescentar nomes parecidos).
    lista = distritos_lista if distritos_lista is not None else detetar_distritos(distritos_texto, provincia)
    for distrito in lista:
        distrito_id = obter_ou_criar_id(conn, 'distritos', distrito)
        conn.execute('INSERT OR IGNORE INTO ong_distritos (ong_id, distrito_id) VALUES (?, ?)',
                     (ong_id, distrito_id))
    for area in detetar_areas(area_texto):
        area_id = obter_ou_criar_id(conn, 'areas', area)
        conn.execute('INSERT OR IGNORE INTO ong_areas (ong_id, area_id) VALUES (?, ?)',
                     (ong_id, area_id))
    for ramificacao in detetar_ramificacoes(area_texto):
        area_da_ramificacao = SUB_PARA_AREA.get(ramificacao)
        if not area_da_ramificacao:
            continue
        area_id = obter_ou_criar_id(conn, 'areas', area_da_ramificacao)
        ramificacao_id = obter_ou_criar_ramificacao_id(conn, ramificacao, area_id)
        conn.execute('INSERT OR IGNORE INTO ong_ramificacoes (ong_id, ramificacao_id) VALUES (?, ?)',
                     (ong_id, ramificacao_id))


def sincronizar_provincias(conn, ong_id, provincias):
    """Guarda o conjunto de províncias onde a organização actua. Uma
    organização pode actuar em várias províncias em simultâneo."""
    conn.execute('DELETE FROM ong_provincias WHERE ong_id = ?', (ong_id,))
    for provincia in provincias or []:
        provincia = provincia.strip()
        if provincia:
            conn.execute('INSERT OR IGNORE INTO ong_provincias (ong_id, provincia) VALUES (?, ?)',
                         (ong_id, provincia))


def sincronizar_naturezas(conn, ong_id, natureza_texto):
    """Guarda cada natureza separadamente (uma organização pode ser, por
    exemplo, 'ONG' e 'OSC' ao mesmo tempo)."""
    conn.execute('DELETE FROM ong_naturezas WHERE ong_id = ?', (ong_id,))
    for n in (natureza_texto or '').split(','):
        n = n.strip()
        if n:
            conn.execute('INSERT OR IGNORE INTO ong_naturezas (ong_id, natureza) VALUES (?, ?)',
                         (ong_id, n))


def obter_provincias_da_ong(conn, ong_id):
    linhas = conn.execute(
        'SELECT provincia FROM ong_provincias WHERE ong_id = ? ORDER BY provincia', (ong_id,)
    ).fetchall()
    return [l['provincia'] for l in linhas]


def obter_listas_filtro(conn, provincia=None, area_id=None):
    if provincia:
        distritos = conn.execute(
            'SELECT id, nome FROM distritos WHERE provincia = ? ORDER BY nome', (provincia,)
        ).fetchall()
    else:
        distritos = conn.execute('SELECT id, nome FROM distritos ORDER BY nome').fetchall()
    areas = conn.execute('SELECT id, nome FROM areas ORDER BY nome').fetchall()
    if area_id:
        ramificacoes = conn.execute(
            'SELECT id, nome FROM ramificacoes WHERE area_id = ? ORDER BY nome', (area_id,)
        ).fetchall()
    else:
        ramificacoes = conn.execute('SELECT id, nome FROM ramificacoes ORDER BY nome').fetchall()
    return distritos, areas, ramificacoes


@app.route('/')
def inicio():
    conn = get_connection()

    total_ongs = conn.execute("SELECT COUNT(*) c FROM ongs WHERE aprovacao='Aprovado'").fetchone()['c']
    total_provincias = conn.execute('SELECT COUNT(DISTINCT provincia) c FROM ong_provincias').fetchone()['c']
    total_distritos = conn.execute('SELECT COUNT(DISTINCT distrito_id) c FROM ong_distritos').fetchone()['c']
    total_areas = conn.execute('SELECT COUNT(DISTINCT area_id) c FROM ong_areas').fetchone()['c']

    por_provincia = conn.execute('''
        SELECT op.provincia, COUNT(DISTINCT op.ong_id) c FROM ong_provincias op
        JOIN ongs o ON o.id = op.ong_id
        WHERE o.aprovacao = 'Aprovado'
        GROUP BY op.provincia ORDER BY c DESC
    ''').fetchall()

    recentes = conn.execute('''
        SELECT id, nome, provincia, natureza, criado_em, logo_url FROM ongs
        WHERE aprovacao = 'Aprovado'
        ORDER BY criado_em DESC LIMIT 5
    ''').fetchall()

    _, ultimas = obter_noticias_inicio(conn)
    capa_url = obter_config(conn, 'capa_inicio') or url_for('static', filename='img/capa_inicio_padrao.jpg')

    conn.close()
    return render_template('inicio.html',
                            capa_url=capa_url, hoje=hoje_extenso(), ultimas=ultimas,
                            total_ongs=total_ongs,
                            total_provincias=total_provincias,
                            total_distritos=total_distritos,
                            total_areas=total_areas,
                            por_provincia=por_provincia,
                            recentes=recentes)



# ─── NOTÍCIAS ─────────────────────────────────────────────────────────────────
PASTA_NOTICIAS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads', 'noticias')
EXTENSOES_NOTICIA = {'.png', '.jpg', '.jpeg', '.webp'}
TAMANHO_MAXIMO_NOTICIA = 5 * 1024 * 1024  # 5 MB
CATEGORIAS_NOTICIA = ['Moçambique', 'Sociedade Civil', 'Desenvolvimento', 'Saúde', 'Educação',
                      'Agricultura', 'Ambiente', 'Parcerias', 'Avisos do Sistema']
MESES_PT = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho', 'Julho', 'Agosto',
            'Setembro', 'Outubro', 'Novembro', 'Dezembro']


@app.template_filter('data_extenso')
def filtro_data_extenso(valor):
    """'2026-10-13 09:30:00' -> '13 de Outubro de 2026'."""
    try:
        d = datetime.strptime(str(valor)[:10], '%Y-%m-%d')
        return f'{d.day} de {MESES_PT[d.month - 1]} de {d.year}'
    except (ValueError, TypeError):
        return ''


@app.template_filter('paragrafos')
def filtro_paragrafos(texto):
    """Texto simples -> parágrafos HTML. Tudo é escapado primeiro, por isso
    nunca entra HTML/JavaScript através do editor de notícias."""
    blocos = [b.strip() for b in (texto or '').replace('\r\n', '\n').split('\n\n') if b.strip()]
    return Markup(''.join('<p>' + str(escape(b)).replace('\n', '<br>') + '</p>' for b in blocos))


def hoje_extenso():
    """Data de hoje em Maputo (UTC+2), por extenso — usada como valor inicial
    na faixa do início; o navegador substitui-a pela data do dispositivo."""
    from datetime import timezone
    d = datetime.now(timezone(timedelta(hours=2)))
    return f'{d.day} de {MESES_PT[d.month - 1]} de {d.year}'


def obter_config(conn, chave, defeito=None):
    r = conn.execute('SELECT valor FROM configuracoes WHERE chave = ?', (chave,)).fetchone()
    return r['valor'] if r and r['valor'] else defeito


def obter_noticias_inicio(conn):
    """As 3 notícias a mostrar no início: a marcada como destaque primeiro,
    depois as mais recentes."""
    ultimas = conn.execute("SELECT * FROM noticias WHERE publicada = 1 "
                           "ORDER BY destaque DESC, publicado_em DESC, id DESC LIMIT 3").fetchall()
    return None, ultimas


def processar_upload_noticia(arquivo, imagem_actual=None):
    """Valida e grava a imagem de capa da notícia -> (url, erro)."""
    if not arquivo or not arquivo.filename:
        return imagem_actual, None
    extensao = os.path.splitext(secure_filename(arquivo.filename))[1].lower()
    if extensao not in EXTENSOES_NOTICIA:
        return imagem_actual, 'Formato de imagem não suportado — use JPG, PNG ou WEBP.'
    arquivo.stream.seek(0, os.SEEK_END)
    tamanho = arquivo.stream.tell()
    arquivo.stream.seek(0)
    if tamanho == 0:
        return imagem_actual, None
    if tamanho > TAMANHO_MAXIMO_NOTICIA:
        return imagem_actual, 'A imagem não pode ultrapassar 5 MB.'
    os.makedirs(PASTA_NOTICIAS, exist_ok=True)
    nome_final = f'{uuid.uuid4().hex}{extensao}'
    arquivo.save(os.path.join(PASTA_NOTICIAS, nome_final))
    return url_for('static', filename=f'uploads/noticias/{nome_final}'), None


def _dados_noticia(form):
    pub = (form.get('publicado_em') or '').strip()
    try:
        pub = datetime.strptime(pub, '%Y-%m-%d').strftime('%Y-%m-%d 00:00:00')
    except ValueError:
        pub = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return {
        'titulo': form.get('titulo', '').strip()[:200],
        'categoria': (form.get('categoria') or 'Moçambique').strip()[:60],
        'resumo': (form.get('resumo') or '').strip()[:400] or None,
        'conteudo': (form.get('conteudo') or '').strip() or None,
        'autor': (form.get('autor') or '').strip()[:100] or None,
        'publicada': 0 if form.get('acao') == 'rascunho' else 1,
        'destaque': 1 if form.get('destaque') else 0,
        'publicado_em': pub,
    }


@app.route('/noticias')
def noticias_lista():
    categoria = request.args.get('categoria', '').strip()
    pagina = max(request.args.get('p', 1, type=int), 1)
    por_pagina = 9
    conn = get_connection()
    cond, params = 'publicada = 1', []
    if categoria:
        cond += ' AND categoria = ?'
        params.append(categoria)
    total = conn.execute(f'SELECT COUNT(*) c FROM noticias WHERE {cond}', params).fetchone()['c']
    itens = conn.execute(
        f'SELECT * FROM noticias WHERE {cond} ORDER BY publicado_em DESC, id DESC LIMIT ? OFFSET ?',
        params + [por_pagina, (pagina - 1) * por_pagina]).fetchall()
    categorias = [r['categoria'] for r in conn.execute(
        'SELECT DISTINCT categoria FROM noticias WHERE publicada = 1 ORDER BY categoria').fetchall()]
    conn.close()
    return render_template('noticias.html', noticias=itens, categorias=categorias, categoria=categoria,
                            pagina=pagina, total_paginas=max(math.ceil(total / por_pagina), 1))


@app.route('/noticias/<int:noticia_id>')
def noticia_detalhe(noticia_id):
    conn = get_connection()
    n = conn.execute('SELECT * FROM noticias WHERE id = ?', (noticia_id,)).fetchone()
    if not n or (not n['publicada'] and not session.get('nivel')):
        conn.close()
        abort(404)
    relacionadas = conn.execute(
        'SELECT id, titulo, imagem_url, publicado_em, categoria FROM noticias '
        'WHERE publicada = 1 AND id != ? ORDER BY publicado_em DESC LIMIT 3', (noticia_id,)).fetchall()
    conn.close()
    return render_template('noticia.html', n=n, relacionadas=relacionadas)


@app.route('/admin/noticias')
@login_obrigatorio
@requer_permissao('gerir_noticias')
def noticias_admin():
    conn = get_connection()
    itens = conn.execute('SELECT * FROM noticias ORDER BY publicado_em DESC, id DESC').fetchall()
    capa_url = obter_config(conn, 'capa_inicio')
    conn.close()
    return render_template('noticias_admin.html', noticias=itens, capa_url=capa_url)


def _formulario_noticia(noticia_id=None):
    conn = get_connection()
    n = None
    if noticia_id:
        n = conn.execute('SELECT * FROM noticias WHERE id = ?', (noticia_id,)).fetchone()
        if not n:
            conn.close()
            flash('Notícia não encontrada.', 'warning')
            return redirect(url_for('noticias_admin'))
    if request.method == 'POST':
        dados = _dados_noticia(request.form)
        ficheiro = request.files.get('imagem')
        imagem, erro = processar_upload_noticia(ficheiro, n['imagem_url'] if n else None)
        if request.form.get('remover_imagem') and not (ficheiro and ficheiro.filename):
            imagem = None
        if not dados['titulo']:
            erro = 'Indique o título da notícia.'
        if erro:
            flash(erro, 'danger')
            conn.close()
            return render_template('noticia_form.html', n={**dados, 'id': noticia_id, 'imagem_url': imagem},
                                    categorias=CATEGORIAS_NOTICIA, edicao=bool(noticia_id))
        utilizador = session.get('utilizador')
        dados['autor'] = dados['autor'] or utilizador
        if dados['destaque']:
            conn.execute('UPDATE noticias SET destaque = 0')
        if n:
            conn.execute("UPDATE noticias SET titulo=?, categoria=?, resumo=?, conteudo=?, autor=?, publicada=?, "
                         "destaque=?, publicado_em=?, imagem_url=?, actualizado_em=datetime('now') WHERE id=?",
                         (dados['titulo'], dados['categoria'], dados['resumo'], dados['conteudo'], dados['autor'],
                          dados['publicada'], dados['destaque'], dados['publicado_em'], imagem, noticia_id))
            accao, verbo = 'editar_noticia', 'editou'
        else:
            conn.execute("INSERT INTO noticias (titulo, categoria, resumo, conteudo, autor, publicada, destaque, "
                         "publicado_em, imagem_url, criado_por) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (dados['titulo'], dados['categoria'], dados['resumo'], dados['conteudo'], dados['autor'],
                          dados['publicada'], dados['destaque'], dados['publicado_em'], imagem, utilizador))
            accao, verbo = 'criar_noticia', 'criou'
        auditoria.registar(conn, accao, f'{utilizador} {verbo} a notícia "{dados["titulo"]}" '
                                         f'({"publicada" if dados["publicada"] else "rascunho"})',
                            utilizador=utilizador, ip=request.remote_addr)
        conn.commit()
        conn.close()
        flash('Notícia publicada.' if dados['publicada'] else 'Notícia guardada como rascunho (não visível ao público).', 'success')
        return redirect(url_for('noticias_admin'))
    conn.close()
    return render_template('noticia_form.html', n=n, categorias=CATEGORIAS_NOTICIA, edicao=bool(noticia_id))


@app.route('/admin/capa', methods=['POST'])
@login_obrigatorio
@requer_permissao('gerir_noticias')
def capa_inicio_guardar():
    conn = get_connection()
    actual = obter_config(conn, 'capa_inicio')
    ficheiro = request.files.get('imagem')
    if request.form.get('remover') and not (ficheiro and ficheiro.filename):
        nova, erro = None, None
    else:
        nova, erro = processar_upload_noticia(ficheiro, actual)
    if erro:
        flash(erro, 'danger')
    else:
        conn.execute('INSERT INTO configuracoes (chave, valor) VALUES (?, ?) '
                     'ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor', ('capa_inicio', nova))
        auditoria.registar(conn, 'alterar_capa', f'{session.get("utilizador")} alterou a imagem de capa da página inicial',
                            utilizador=session.get('utilizador'), ip=request.remote_addr)
        conn.commit()
        flash('Imagem de capa actualizada.', 'success')
    conn.close()
    return redirect(url_for('noticias_admin'))


@app.route('/admin/noticias/nova', methods=['GET', 'POST'])
@login_obrigatorio
@requer_permissao('gerir_noticias')
def noticia_nova():
    return _formulario_noticia()


@app.route('/admin/noticias/<int:noticia_id>/editar', methods=['GET', 'POST'])
@login_obrigatorio
@requer_permissao('gerir_noticias')
def noticia_editar(noticia_id):
    return _formulario_noticia(noticia_id)


@app.route('/admin/noticias/<int:noticia_id>/publicar', methods=['POST'])
@login_obrigatorio
@requer_permissao('gerir_noticias')
def noticia_publicar(noticia_id):
    conn = get_connection()
    n = conn.execute('SELECT titulo, publicada FROM noticias WHERE id = ?', (noticia_id,)).fetchone()
    if n:
        novo = 0 if n['publicada'] else 1
        conn.execute('UPDATE noticias SET publicada = ? WHERE id = ?', (novo, noticia_id))
        auditoria.registar(conn, 'publicar_noticia',
                            f'{session.get("utilizador")} {"publicou" if novo else "retirou do site"} a notícia "{n["titulo"]}"',
                            utilizador=session.get('utilizador'), ip=request.remote_addr)
        conn.commit()
    conn.close()
    return redirect(url_for('noticias_admin'))


@app.route('/admin/noticias/<int:noticia_id>/eliminar', methods=['POST'])
@login_obrigatorio
@requer_permissao('gerir_noticias')
def noticia_eliminar(noticia_id):
    conn = get_connection()
    n = conn.execute('SELECT titulo FROM noticias WHERE id = ?', (noticia_id,)).fetchone()
    if n:
        conn.execute('DELETE FROM noticias WHERE id = ?', (noticia_id,))
        auditoria.registar(conn, 'eliminar_noticia', f'{session.get("utilizador")} eliminou a notícia "{n["titulo"]}"',
                            utilizador=session.get('utilizador'), ip=request.remote_addr)
        conn.commit()
        flash('Notícia eliminada.', 'info')
    conn.close()
    return redirect(url_for('noticias_admin'))


@app.route('/chatbot/perguntar')
def chatbot_perguntar():
    """Assistente de perguntas rápidas (público, só leitura)."""
    conn = get_connection()
    resposta = chatbot.responder(conn, request.args.get('q', '')[:200])
    conn.close()
    return jsonify(resposta)


@app.route('/ongs')
def index():
    conn = get_connection()

    q = request.args.get('q', '').strip()
    origem = request.args.get('origem', '').strip()
    natureza = request.args.get('natureza', '').strip()
    estado = request.args.get('estado', '').strip()
    provincia = request.args.get('provincia', '').strip()
    escopo_provincia = provincia_sessao()
    if escopo_provincia:
        provincia = escopo_provincia  # Gestor Provincial não escolhe: está sempre limitado à sua província
    distrito_id = request.args.get('distrito_id', '').strip()
    area_id = request.args.get('area_id', '').strip()
    ramificacao_id = request.args.get('ramificacao_id', '').strip()
    publico_alvo = request.args.get('publico_alvo', '').strip()
    contacto = request.args.get('contacto', '').strip()
    ano_desde = request.args.get('ano_desde', '').strip()
    ano_ate = request.args.get('ano_ate', '').strip()
    pagina = max(1, request.args.get('pagina', 1, type=int))

    condicoes = []
    parametros = []
    joins = ''

    if q:
        condicoes.append('(o.nome LIKE ? OR o.sigla LIKE ?)')
        parametros.append(f'%{q}%')
        parametros.append(f'%{q}%')
    if origem:
        condicoes.append('o.origem = ?')
        parametros.append(origem)
    if natureza:
        condicoes.append('o.natureza LIKE ?')
        parametros.append(f'%{natureza}%')
    if estado:
        condicoes.append('o.estado = ?')
        parametros.append(estado)
    if provincia:
        joins += ' JOIN ong_provincias op ON op.ong_id = o.id '
        condicoes.append('op.provincia = ?')
        parametros.append(provincia)
    if distrito_id:
        joins += ' JOIN ong_distritos od ON od.ong_id = o.id '
        condicoes.append('od.distrito_id = ?')
        parametros.append(distrito_id)
    if area_id:
        joins += ' JOIN ong_areas oa ON oa.ong_id = o.id '
        condicoes.append('oa.area_id = ?')
        parametros.append(area_id)
    if ramificacao_id:
        joins += ' JOIN ong_ramificacoes orf ON orf.ong_id = o.id '
        condicoes.append('orf.ramificacao_id = ?')
        parametros.append(ramificacao_id)
    if publico_alvo:
        condicoes.append('o.perfil_grupo_alvo LIKE ?')
        parametros.append(f'%{publico_alvo}%')
    if contacto:
        condicoes.append('(o.pessoa_contacto LIKE ? OR o.telefone LIKE ? OR o.email LIKE ?)')
        parametros += [f'%{contacto}%', f'%{contacto}%', f'%{contacto}%']
    if ano_desde:
        condicoes.append('o.ano_entrada_pais >= ?')
        parametros.append(ano_desde)
    if ano_ate:
        condicoes.append('o.ano_entrada_pais <= ?')
        parametros.append(ano_ate)

    # Filtro de aprovação:
    # Visitantes e admins normais só veem ONGs aprovadas.
    # O Super Admin pode ver também as pendentes/rejeitadas (com filtro opcional).
    aprovacao_filtro = request.args.get('aprovacao', '').strip()
    if e_super_admin() and aprovacao_filtro:
        condicoes.append('o.aprovacao = ?')
        parametros.append(aprovacao_filtro)
    elif not e_super_admin():
        condicoes.append("o.aprovacao = 'Aprovado'")

    where = f"WHERE {' AND '.join(condicoes)}" if condicoes else ''

    total = conn.execute(
        f'SELECT COUNT(DISTINCT o.id) AS total FROM ongs o {joins} {where}', parametros
    ).fetchone()['total']
    total_paginas = max(1, math.ceil(total / POR_PAGINA))
    pagina = min(pagina, total_paginas)
    offset = (pagina - 1) * POR_PAGINA

    ongs = conn.execute(f'''
        SELECT DISTINCT o.* FROM ongs o {joins} {where}
        ORDER BY o.nome
        LIMIT ? OFFSET ?
    ''', parametros + [POR_PAGINA, offset]).fetchall()

    distritos_para_ongs = {}
    provincias_para_ongs = {}
    if ongs:
        ids = [str(o['id']) for o in ongs]
        linhas = conn.execute(f'''
            SELECT od.ong_id, d.nome FROM ong_distritos od
            JOIN distritos d ON d.id = od.distrito_id
            WHERE od.ong_id IN ({",".join(ids)})
        ''').fetchall()
        for linha in linhas:
            distritos_para_ongs.setdefault(linha['ong_id'], []).append(linha['nome'])

        linhas_prov = conn.execute(f'''
            SELECT ong_id, provincia FROM ong_provincias WHERE ong_id IN ({",".join(ids)})
        ''').fetchall()
        for linha in linhas_prov:
            provincias_para_ongs.setdefault(linha['ong_id'], []).append(linha['provincia'])

    distritos, areas, ramificacoes = obter_listas_filtro(conn, provincia, area_id)
    distritos_por_prov = {}
    for r in conn.execute('SELECT id, nome, provincia FROM distritos WHERE provincia IS NOT NULL ORDER BY nome'):
        distritos_por_prov.setdefault(r['provincia'], []).append({'id': r['id'], 'nome': r['nome']})
    conn.close()

    return render_template('index.html',
                            distritos_por_prov=distritos_por_prov,
                            ongs=ongs,
                            distritos_para_ongs=distritos_para_ongs,
                            provincias_para_ongs=provincias_para_ongs,
                            distritos=distritos,
                            areas=areas,
                            ramificacoes=ramificacoes,
                            provincias=PROVINCIAS,
                            total=total,
                            pagina=pagina,
                            total_paginas=total_paginas,
                            filtros={'q': q, 'origem': origem, 'natureza': natureza, 'estado': estado, 'provincia': provincia,
                                     'distrito_id': distrito_id, 'area_id': area_id, 'ramificacao_id': ramificacao_id,
                                     'publico_alvo': publico_alvo, 'contacto': contacto,
                                     'ano_desde': ano_desde, 'ano_ate': ano_ate})


@app.route('/organizacoes')
def organizacoes():
    conn = get_connection()

    q = request.args.get('q', '').strip()
    provincia_filtro = request.args.get('provincia', '').strip()
    area_filtro = request.args.get('area', '').strip()
    ramificacao_filtro = request.args.get('ramificacao', '').strip()
    distrito_filtro = request.args.get('distrito', '').strip()
    pagina = max(1, request.args.get('pagina', 1, type=int))

    linhas = conn.execute("SELECT id, nome, sigla, natureza, origem, provincia, estado FROM ongs WHERE aprovacao = 'Aprovado'").fetchall()

    # Pré-carregar distritos, áreas, ramificações e províncias de TODAS as
    # ONGs de uma vez (em vez de uma query por organização), para podermos
    # filtrar antes de paginar.
    provincias_por_ong = {}
    for r in conn.execute('SELECT ong_id, provincia FROM ong_provincias'):
        provincias_por_ong.setdefault(r['ong_id'], set()).add(r['provincia'])

    distritos_por_ong = {}
    for r in conn.execute('''
        SELECT od.ong_id, d.nome FROM ong_distritos od JOIN distritos d ON d.id = od.distrito_id
    '''):
        distritos_por_ong.setdefault(r['ong_id'], set()).add(r['nome'])

    areas_por_ong = {}
    for r in conn.execute('''
        SELECT oa.ong_id, a.nome FROM ong_areas oa JOIN areas a ON a.id = oa.area_id
    '''):
        areas_por_ong.setdefault(r['ong_id'], set()).add(r['nome'])

    ramificacoes_por_ong = {}
    for r in conn.execute('''
        SELECT orf.ong_id, r.nome FROM ong_ramificacoes orf JOIN ramificacoes r ON r.id = orf.ramificacao_id
    '''):
        ramificacoes_por_ong.setdefault(r['ong_id'], set()).add(r['nome'])

    # Agrupar por nome (normalizado), juntando as provincias/naturezas/origens/
    # distritos/areas/ramificacoes de cada linha que pertence à mesma organização.
    grupos = {}
    for r in linhas:
        chave = r['nome'].strip().lower()
        grupo = grupos.setdefault(chave, {
            'nome': r['nome'].strip(), 'sigla': r['sigla'], 'ids': [], 'provincias': set(),
            'naturezas': set(), 'origens': set(), 'estados': set(),
            'distritos': set(), 'areas': set(), 'ramificacoes': set(),
        })
        grupo['ids'].append(r['id'])
        grupo['provincias'] |= provincias_por_ong.get(r['id'], set())
        if r['provincia']:
            grupo['provincias'].add(r['provincia'])
        if not grupo.get('sigla') and r['sigla']:
            grupo['sigla'] = r['sigla']
        if r['natureza']:
            for n in r['natureza'].split(','):
                grupo['naturezas'].add(n.strip())
        if r['origem']:
            grupo['origens'].add(r['origem'])
        if r['estado']:
            grupo['estados'].add(r['estado'])
        grupo['distritos'] |= distritos_por_ong.get(r['id'], set())
        grupo['areas'] |= areas_por_ong.get(r['id'], set())
        grupo['ramificacoes'] |= ramificacoes_por_ong.get(r['id'], set())

    lista = list(grupos.values())

    if q:
        q_lower = q.lower()
        lista = [g for g in lista if q_lower in g['nome'].lower() or (g['sigla'] and q_lower in g['sigla'].lower())]
    if provincia_filtro:
        lista = [g for g in lista if provincia_filtro in g['provincias']]
    if area_filtro:
        lista = [g for g in lista if area_filtro in g['areas']]
    if ramificacao_filtro:
        lista = [g for g in lista if ramificacao_filtro in g['ramificacoes']]
    if distrito_filtro:
        lista = [g for g in lista if distrito_filtro in g['distritos']]

    lista.sort(key=lambda g: g['nome'].lower())

    total = len(lista)
    total_paginas = max(1, math.ceil(total / POR_PAGINA))
    pagina = min(pagina, total_paginas)
    pagina_lista = lista[(pagina - 1) * POR_PAGINA: pagina * POR_PAGINA]

    organizacoes_pagina = [{
        'nome': g['nome'],
        'sigla': g['sigla'],
        'ids': g['ids'],
        'num_registos': len(g['ids']),
        'provincias': sorted(g['provincias']),
        'distritos': sorted(g['distritos']),
        'areas': sorted(g['areas']),
        'ramificacoes': sorted(g['ramificacoes']),
        'naturezas': sorted(g['naturezas']),
        'origens': sorted(g['origens']),
        'estados': sorted(g['estados']),
    } for g in pagina_lista]

    ramificacoes_da_area = list(ESTRUTURA_AREAS_TEMATICAS[area_filtro]) if area_filtro in ESTRUTURA_AREAS_TEMATICAS else []

    conn.close()
    return render_template('organizacoes.html',
                            organizacoes=organizacoes_pagina,
                            provincias=PROVINCIAS,
                            areas_tematicas=AREAS_TEMATICAS,
                            ramificacoes_da_area=ramificacoes_da_area,
                            total=total,
                            pagina=pagina,
                            total_paginas=total_paginas,
                            filtros={'q': q, 'provincia': provincia_filtro, 'area': area_filtro,
                                     'ramificacao': ramificacao_filtro, 'distrito': distrito_filtro})


@app.route('/dashboard')
def dashboard():
    conn = get_connection()

    provincia_filtro = request.args.get('provincia', '').strip()
    escopo_provincia = provincia_sessao()
    if escopo_provincia:
        provincia_filtro = escopo_provincia  # Gestor Provincial: dashboard sempre limitado à sua província
    distrito_id_filtro = request.args.get('distrito_id', '').strip()

    # Subconjunto de ONGs que respeita os filtros atuais (provincia e/ou distrito).
    # Construído uma vez e reutilizado em todas as queries de agregação abaixo,
    # para evitar repetir lógica de WHERE/JOIN espalhada pelo código.
    condicoes = ["o.aprovacao = 'Aprovado'"]
    params_sub = []
    join_distrito = ''
    if provincia_filtro:
        # tal como na listagem, nos mapas e nos relatórios: conta TODAS as ONGs que actuam
        # na província (ong_provincias), não só aquelas cuja província "principal" é esta
        condicoes.append('o.id IN (SELECT ong_id FROM ong_provincias WHERE provincia = ?)')
        params_sub.append(provincia_filtro)
    if distrito_id_filtro:
        join_distrito = 'JOIN ong_distritos od_f ON od_f.ong_id = o.id'
        condicoes.append('od_f.distrito_id = ?')
        params_sub.append(distrito_id_filtro)
    where_sub = f"WHERE {' AND '.join(condicoes)}"
    subquery_ids = f'(SELECT DISTINCT o.id FROM ongs o {join_distrito} {where_sub})'

    distritos_filtro, _, _ = obter_listas_filtro(conn, provincia_filtro)
    nome_distrito_filtro = None
    if distrito_id_filtro:
        linha = conn.execute('SELECT nome FROM distritos WHERE id = ?', (distrito_id_filtro,)).fetchone()
        nome_distrito_filtro = linha['nome'] if linha else None

    total_ongs = conn.execute(f'SELECT COUNT(*) c FROM ongs WHERE id IN {subquery_ids}', params_sub).fetchone()['c']

    total_provincias = 1 if provincia_filtro else conn.execute(
        "SELECT COUNT(DISTINCT provincia) c FROM ongs WHERE provincia IS NOT NULL AND provincia != '' AND aprovacao = 'Aprovado'"
    ).fetchone()['c']

    if distrito_id_filtro:
        total_distritos = 1
    elif provincia_filtro:
        # Filtra pela província do PRÓPRIO distrito (tabela distritos), não
        # da ONG — uma ONG multi-província pode ter distritos legitimamente
        # detectados noutras províncias, que não devem contar aqui.
        total_distritos = conn.execute('''
            SELECT COUNT(DISTINCT od.distrito_id) c FROM ong_distritos od
            JOIN distritos d ON d.id = od.distrito_id
            WHERE od.ong_id IN {} AND d.provincia = ?
        '''.format(subquery_ids), params_sub + [provincia_filtro]).fetchone()['c']
    else:
        total_distritos = conn.execute(f'''
            SELECT COUNT(DISTINCT distrito_id) c FROM ong_distritos WHERE ong_id IN {subquery_ids}
        ''', params_sub).fetchone()['c']

    total_areas = conn.execute(f'''
        SELECT COUNT(DISTINCT area_id) c FROM ong_areas WHERE ong_id IN {subquery_ids}
    ''', params_sub).fetchone()['c']

    por_provincia = conn.execute('''
        SELECT op.provincia, COUNT(DISTINCT op.ong_id) c FROM ong_provincias op
        JOIN ongs o ON o.id = op.ong_id
        WHERE o.aprovacao = 'Aprovado'
        GROUP BY op.provincia ORDER BY c DESC
    ''').fetchall()

    total_nacional = conn.execute("SELECT COUNT(*) c FROM ongs WHERE aprovacao='Aprovado'").fetchone()['c']
    maputo_distinto = conn.execute('''
        SELECT COUNT(DISTINCT op.ong_id) c FROM ong_provincias op JOIN ongs o ON o.id = op.ong_id
        WHERE o.aprovacao='Aprovado' AND op.provincia IN ('Maputo Cidade', 'Maputo Província')
    ''').fetchone()['c']
    mapa_dados = [{'nome': r['provincia'], 'total': r['c'],
                   'pct': round(r['c'] / total_nacional * 100, 1) if total_nacional else 0}
                  for r in por_provincia]

    mapa_distritos = [dict(r) for r in conn.execute('''
        SELECT d.id, d.nome, d.provincia,
               COUNT(DISTINCT CASE WHEN o.id IS NOT NULL THEN od.ong_id END) AS total
        FROM distritos d
        LEFT JOIN ong_distritos od ON od.distrito_id = d.id
        LEFT JOIN ongs o ON o.id = od.ong_id AND o.aprovacao = 'Aprovado'
        GROUP BY d.id
    ''').fetchall()]

    por_area = conn.execute(f'''
        SELECT a.nome, COUNT(*) c FROM ong_areas oa
        JOIN areas a ON a.id = oa.area_id
        WHERE oa.ong_id IN {subquery_ids}
        GROUP BY a.nome ORDER BY c DESC
    ''', params_sub).fetchall()

    # Origem: incluímos um balde "Não especificado" para as organizações sem
    # este campo preenchido — assim a soma do gráfico bate sempre certo com
    # o total de organizações apresentado na listagem (correção do relatório
    # de recomendações: "o somatório... não corresponde ao número total").
    por_origem = conn.execute(f'''
        SELECT COALESCE(NULLIF(TRIM(origem), ''), 'Não especificado') AS origem, COUNT(*) c
        FROM ongs WHERE id IN {subquery_ids}
        GROUP BY 1 ORDER BY c DESC
    ''', params_sub).fetchall()

    por_estado = conn.execute(f'''
        SELECT estado, COUNT(*) c FROM ongs WHERE id IN {subquery_ids} GROUP BY estado ORDER BY c DESC
    ''', params_sub).fetchall()

    # Natureza: uma organização pode ter mais do que uma natureza (ex.: "ONG,
    # OSC"), por isso contamos a partir de ong_naturezas (uma linha por
    # natureza) em vez de comparações LIKE sobrepostas. Isto corrige o
    # gráfico de pizza que somava mais organizações do que as existentes.
    # Como uma organização pode aparecer em mais do que uma fatia, a soma
    # das fatias pode ultrapassar o total de organizações — isso é esperado
    # e está identificado na legenda do gráfico.
    linhas_natureza = conn.execute(f'''
        SELECT natureza, COUNT(DISTINCT ong_id) c FROM ong_naturezas
        WHERE ong_id IN {subquery_ids}
        GROUP BY natureza ORDER BY c DESC
    ''', params_sub).fetchall()
    natureza_contagens = {r['natureza']: r['c'] for r in linhas_natureza}
    sem_natureza = conn.execute(f'''
        SELECT COUNT(*) c FROM ongs
        WHERE id IN {subquery_ids} AND id NOT IN (SELECT ong_id FROM ong_naturezas)
    ''', params_sub).fetchone()['c']
    if sem_natureza:
        natureza_contagens['Não especificado'] = sem_natureza

    # Ramificações: para cada área temática, contamos quantas ONGs mencionam
    # cada uma das suas ramificações (sub-categorias) oficiais. As ramificações
    # sem nenhuma ONG aparecem com 0 (em vez de desaparecerem), e a ordem
    # segue sempre a taxonomia oficial, não a contagem.
    sub_para_area = {sub: area for area, subs in ESTRUTURA_AREAS_TEMATICAS.items() for sub in subs}

    textos = conn.execute(f'''
        SELECT area_intervencao FROM ongs WHERE id IN {subquery_ids} AND area_intervencao IS NOT NULL
    ''', params_sub).fetchall()

    contagem_ramificacoes = {area: {sub: 0 for sub in subs} for area, subs in ESTRUTURA_AREAS_TEMATICAS.items()}
    for linha in textos:
        for sub in detetar_ramificacoes(linha['area_intervencao']):
            contagem_ramificacoes[sub_para_area[sub]][sub] += 1

    total_ongs_por_area = {r['nome']: r['c'] for r in por_area}

    ramificacoes = {
        area: [(sub, contagem_ramificacoes[area][sub]) for sub in ESTRUTURA_AREAS_TEMATICAS[area]]
        for area in ESTRUTURA_AREAS_TEMATICAS
    }

    # ---- Chips de estado do workflow (só faz sentido para quem gere) ----
    cond_estado_geral = ['1=1']
    params_estado = []
    if provincia_filtro:
        cond_estado_geral.append('id IN (SELECT ong_id FROM ong_provincias WHERE provincia = ?)')
        params_estado.append(provincia_filtro)
    where_estado_geral = ' AND '.join(cond_estado_geral)
    total_registadas = conn.execute(
        f'SELECT COUNT(*) c FROM ongs WHERE {where_estado_geral} AND rascunho = 0', params_estado
    ).fetchone()['c']
    total_pendentes_geral = conn.execute(
        f"SELECT COUNT(*) c FROM ongs WHERE {where_estado_geral} AND aprovacao = 'Pendente'", params_estado
    ).fetchone()['c']
    total_rejeitadas_geral = conn.execute(
        f"SELECT COUNT(*) c FROM ongs WHERE {where_estado_geral} AND aprovacao = 'Rejeitado'", params_estado
    ).fetchone()['c']

    # ---- Evolução anual (registos aprovados, por ano de criação) ----
    registos_por_ano = conn.execute(f'''
        SELECT strftime('%Y', criado_em) AS ano, COUNT(*) c FROM ongs
        WHERE id IN {subquery_ids} AND criado_em IS NOT NULL
        GROUP BY ano ORDER BY ano
    ''', params_sub).fetchall()

    # ---- ONGs por distrito (top 15) ----
    cond_distrito_provincia = 'AND d.provincia = ?' if provincia_filtro else ''
    params_distrito = params_sub + ([provincia_filtro] if provincia_filtro else [])
    por_distrito = conn.execute(f'''
        SELECT d.nome, COUNT(DISTINCT od.ong_id) c
        FROM ong_distritos od
        JOIN distritos d ON d.id = od.distrito_id
        WHERE od.ong_id IN {subquery_ids} {cond_distrito_provincia}
        GROUP BY d.nome ORDER BY c DESC LIMIT 15
    ''', params_distrito).fetchall()

    # ---- ONGs por distrito, com repartição por natureza (ONG/OSC/Fundação) ----
    distrito_natureza = conn.execute(f'''
        SELECT d.nome AS distrito,
               COUNT(DISTINCT CASE WHEN on2.natureza = 'ONG' THEN od.ong_id END) AS total_ong,
               COUNT(DISTINCT CASE WHEN on2.natureza = 'OSC' THEN od.ong_id END) AS total_osc,
               COUNT(DISTINCT CASE WHEN on2.natureza = 'Fundação' THEN od.ong_id END) AS total_fundacao,
               COUNT(DISTINCT od.ong_id) AS total_geral
        FROM ong_distritos od
        JOIN distritos d ON d.id = od.distrito_id
        LEFT JOIN ong_naturezas on2 ON on2.ong_id = od.ong_id
        WHERE od.ong_id IN {subquery_ids} {cond_distrito_provincia}
        GROUP BY d.nome ORDER BY total_geral DESC LIMIT 20
    ''', params_distrito).fetchall()

    # ---- Cobertura territorial ----
    total_distritos_oficiais = sum(len(v) for v in DISTRITOS_POR_PROVINCIA.values())
    if provincia_filtro:
        distritos_oficiais_ref = len(DISTRITOS_POR_PROVINCIA.get(provincia_filtro, []))
        cobertura_provincias = 100.0
    else:
        distritos_oficiais_ref = total_distritos_oficiais
        cobertura_provincias = round(total_provincias / len(PROVINCIAS) * 100, 1)
    cobertura_distritos = round((total_distritos / distritos_oficiais_ref * 100), 1) if distritos_oficiais_ref else 0

    conn.close()

    return render_template('dashboard.html',
                            provincias=PROVINCIAS,
                            provincia_filtro=provincia_filtro,
                            distritos_filtro=distritos_filtro,
                            distrito_id_filtro=distrito_id_filtro,
                            nome_distrito_filtro=nome_distrito_filtro,
                            total_ongs=total_ongs,
                            total_provincias=total_provincias,
                            total_distritos=total_distritos,
                            total_areas=total_areas,
                            total_registadas=total_registadas,
                            total_pendentes_geral=total_pendentes_geral,
                            total_rejeitadas_geral=total_rejeitadas_geral,
                            ano_labels=[r['ano'] for r in registos_por_ano],
                            ano_valores=[r['c'] for r in registos_por_ano],
                            distrito_labels=[r['nome'] for r in por_distrito],
                            distrito_valores=[r['c'] for r in por_distrito],
                            distrito_natureza=distrito_natureza,
                            mapa_dados=mapa_dados, mapa_distritos=mapa_distritos, total_nacional=total_nacional, maputo_distinto=maputo_distinto,
                            cobertura_provincias=cobertura_provincias,
                            cobertura_distritos=cobertura_distritos,
                            total_distritos_oficiais=distritos_oficiais_ref,
                            provincia_labels=[r['provincia'] for r in por_provincia],
                            provincia_valores=[r['c'] for r in por_provincia],
                            area_labels=[r['nome'] for r in por_area],
                            area_valores=[r['c'] for r in por_area],
                            origem_labels=[r['origem'] for r in por_origem],
                            origem_valores=[r['c'] for r in por_origem],
                            estado_labels=[r['estado'] for r in por_estado],
                            estado_valores=[r['c'] for r in por_estado],
                            natureza_labels=list(natureza_contagens.keys()),
                            natureza_valores=list(natureza_contagens.values()),
                            ramificacoes=ramificacoes,
                            total_ongs_por_area=total_ongs_por_area)


@app.route('/levantamento-nacional')
def levantamento_nacional():
    """Resumo do levantamento nacional de ONGs/OSCs/Fundações feito pelo MPD
    (Ministério da Planificação e Desenvolvimento), com base na apresentação
    'Levantamento de ONG's que Operam no País' (Maputo, 29 de Abril de 2026).
    Os números aqui são fixos (vêm da apresentação, não da base de dados do
    SGIONGs) e servem como contexto nacional complementar à listagem interna.
    """
    natureza_labels = ['ONGs', 'OSCs/Associações', 'Fundações']
    natureza_valores = [580, 169, 52]

    origem_labels = ['Estrangeiras/Internacionais', 'Nacionais']
    origem_valores = [318, 176]

    provincia_labels = ['Maputo', 'Cabo Delgado', 'Sofala', 'Niassa', 'Gaza',
                         'Zambézia', 'Inhambane', 'Nampula', 'Manica', 'Tete']
    provincia_valores = [235, 131, 81, 75, 74, 55, 57, 34, 31, 28]

    sector_labels = ['Saúde', 'Agricultura e Segurança Alimentar', 'Educação',
                      'Acção Social', 'Outras', 'Conservação e Meio Ambiente',
                      'Infraestruturas', 'Ajuda Humanitária',
                      'Resiliência e Mudanças Climáticas', 'Pecuária']
    sector_valores = [226, 218, 109, 109, 66, 76, 59, 55, 6, 2]

    constatacoes = [
        'Das três categorias de actores locais analisadas, as ONGs são as mais numerosas, '
        'seguidas pelas Organizações da Sociedade Civil/Associações e, por último, pelas Fundações.',
        'A maior parte das ONGs identificadas é de origem estrangeira e está espalhada por '
        'praticamente todo o país.',
        'Maputo, Cabo Delgado e Sofala são as províncias com maior concentração de ONGs.',
        'Agricultura, Saúde e Educação são os sectores de actividade mais frequentes entre '
        'as organizações mapeadas.',
        'Cabo Delgado destaca-se pelo maior número de projectos de infra-estruturas sanitárias, '
        'escolares e agrárias, de reassentamento, de assistência a vítimas de eventos climáticos '
        'extremos e de ajuda humanitária.',
    ]

    return render_template('levantamento.html',
                            natureza_labels=natureza_labels,
                            natureza_valores=natureza_valores,
                            origem_labels=origem_labels,
                            origem_valores=origem_valores,
                            provincia_labels=provincia_labels,
                            provincia_valores=provincia_valores,
                            sector_labels=sector_labels,
                            sector_valores=sector_valores,
                            constatacoes=constatacoes,
                            total_geral=sum(natureza_valores))


@app.route('/pendentes')
@login_obrigatorio
@requer_permissao('aprovar')
def pendentes():
    escopo_provincia = provincia_sessao()
    conn = get_connection()
    if escopo_provincia:
        ongs_pendentes = conn.execute('''
            SELECT * FROM ongs WHERE aprovacao = 'Pendente' AND provincia = ?
            ORDER BY criado_em DESC
        ''', (escopo_provincia,)).fetchall()
        edicoes_pendentes_linhas = conn.execute('''
            SELECT ap.*, o.nome AS ong_nome, o.sigla AS ong_sigla
            FROM alteracoes_pendentes ap
            JOIN ongs o ON o.id = ap.ong_id
            WHERE ap.estado = 'Pendente' AND o.provincia = ?
            ORDER BY ap.solicitado_em DESC
        ''', (escopo_provincia,)).fetchall()
    else:
        ongs_pendentes = conn.execute('''
            SELECT * FROM ongs WHERE aprovacao = 'Pendente' ORDER BY criado_em DESC
        ''').fetchall()
        edicoes_pendentes_linhas = conn.execute('''
            SELECT ap.*, o.nome AS ong_nome, o.sigla AS ong_sigla
            FROM alteracoes_pendentes ap
            JOIN ongs o ON o.id = ap.ong_id
            WHERE ap.estado = 'Pendente'
            ORDER BY ap.solicitado_em DESC
        ''').fetchall()
    edicoes_pendentes = []
    for linha in edicoes_pendentes_linhas:
        diffs = _diferencas(json.loads(linha['dados_antigos_json']), json.loads(linha['dados_json']))
        edicoes_pendentes.append({'alteracao': linha, 'diffs': diffs})
    conn.close()
    return render_template('pendentes.html', ongs=ongs_pendentes, edicoes_pendentes=edicoes_pendentes)


@app.route('/ong/<int:ong_id>/aprovar', methods=['POST'])
@login_obrigatorio
@requer_permissao('aprovar')
def aprovar(ong_id):
    conn = get_connection()
    conn.execute('BEGIN IMMEDIATE')  # serializa: duas pessoas a decidir o mesmo registo em simultâneo
    ong = conn.execute('SELECT nome, criado_por, provincia, aprovacao, rascunho FROM ongs WHERE id = ?', (ong_id,)).fetchone()
    if not ong:
        conn.close()
        flash('ONG não encontrada.', 'warning')
        return redirect(url_for('pendentes'))
    if ong['aprovacao'] != 'Pendente' or ong['rascunho']:
        # só se aprova/rejeita o que está realmente submetido e pendente
        conn.close()
        flash('Este registo não está pendente de aprovação.', 'warning')
        return redirect(url_for('pendentes'))

    escopo_provincia = provincia_sessao()
    if escopo_provincia and ong['provincia'] != escopo_provincia:
        conn.close()
        flash('Esta ONG está fora da sua província de gestão.', 'danger')
        return redirect(url_for('pendentes'))

    if not perfis.pode_aprovar_registo(session.get('utilizador'), ong['criado_por']):
        conn.close()
        flash('Não pode aprovar um registo que submeteu. Peça a outro utilizador para rever.', 'danger')
        return redirect(url_for('pendentes'))

    conn.execute('''
        UPDATE ongs SET aprovacao='Aprovado', aprovado_por=?, aprovado_em=?, motivo_rejeicao=NULL,
            fase_workflow='Publicada', em_analise_por=NULL, em_analise_em=NULL
        WHERE id=?
    ''', (session.get('utilizador'), datetime.now().strftime('%Y-%m-%d %H:%M:%S'), ong_id))
    auditoria.registar(conn, 'aprovar_ong', f'{session.get("utilizador")} aprovou o registo da ONG "{ong["nome"]}"',
                        utilizador=session.get('utilizador'), ip=request.remote_addr, ong_id=ong_id)
    conn.commit()
    conn.close()
    flash('ONG aprovada com sucesso.', 'success')
    return redirect(request.referrer or url_for('pendentes'))


@app.route('/ong/<int:ong_id>/rejeitar', methods=['POST'])
@login_obrigatorio
@requer_permissao('aprovar')
def rejeitar(ong_id):
    motivo = request.form.get('motivo', '').strip() or 'Sem motivo indicado'
    conn = get_connection()
    conn.execute('BEGIN IMMEDIATE')  # serializa: duas pessoas a decidir o mesmo registo em simultâneo
    ong = conn.execute('SELECT nome, criado_por, provincia, aprovacao, rascunho FROM ongs WHERE id = ?', (ong_id,)).fetchone()
    if not ong:
        conn.close()
        flash('ONG não encontrada.', 'warning')
        return redirect(url_for('pendentes'))
    if ong['aprovacao'] != 'Pendente' or ong['rascunho']:
        # só se aprova/rejeita o que está realmente submetido e pendente
        conn.close()
        flash('Este registo não está pendente de aprovação.', 'warning')
        return redirect(url_for('pendentes'))

    escopo_provincia = provincia_sessao()
    if escopo_provincia and ong['provincia'] != escopo_provincia:
        conn.close()
        flash('Esta ONG está fora da sua província de gestão.', 'danger')
        return redirect(url_for('pendentes'))

    if not perfis.pode_aprovar_registo(session.get('utilizador'), ong['criado_por']):
        conn.close()
        flash('Não pode rejeitar um registo que submeteu. Peça a outro utilizador para rever.', 'danger')
        return redirect(url_for('pendentes'))

    conn.execute('''
        UPDATE ongs SET aprovacao='Rejeitado', aprovado_por=?, aprovado_em=?, motivo_rejeicao=?,
            fase_workflow=NULL, em_analise_por=NULL, em_analise_em=NULL
        WHERE id=?
    ''', (session.get('utilizador'), datetime.now().strftime('%Y-%m-%d %H:%M:%S'), motivo, ong_id))
    auditoria.registar(conn, 'rejeitar_ong',
                        f'{session.get("utilizador")} rejeitou o registo da ONG "{ong["nome"]}" — motivo: {motivo}',
                        utilizador=session.get('utilizador'), ip=request.remote_addr, ong_id=ong_id, detalhes={'motivo': motivo})
    conn.commit()
    conn.close()
    flash(f'ONG rejeitada. Motivo: {motivo}', 'danger')
    return redirect(request.referrer or url_for('pendentes'))


@app.route('/alteracao/<int:alteracao_id>/aprovar', methods=['POST'])
@login_obrigatorio
@requer_permissao('aprovar')
def aprovar_edicao(alteracao_id):
    conn = get_connection()
    conn.execute('BEGIN IMMEDIATE')  # serializa: duas pessoas a decidir o mesmo registo em simultâneo
    alteracao = conn.execute('''
        SELECT ap.*, o.provincia AS ong_provincia, o.nome AS ong_nome, o.aprovacao AS ong_aprovacao
        FROM alteracoes_pendentes ap
        JOIN ongs o ON o.id = ap.ong_id
        WHERE ap.id = ? AND ap.estado = 'Pendente'
    ''', (alteracao_id,)).fetchone()
    if not alteracao:
        conn.close()
        flash('Esta alteração já foi tratada ou não existe.', 'warning')
        return redirect(url_for('pendentes'))

    escopo_provincia = provincia_sessao()
    if escopo_provincia and alteracao['ong_provincia'] != escopo_provincia:
        conn.close()
        flash('Esta ONG está fora da sua província de gestão.', 'danger')
        return redirect(url_for('pendentes'))

    if not perfis.pode_aprovar_registo(session.get('utilizador'), alteracao['solicitado_por']):
        conn.close()
        flash('Não pode aprovar uma edição que você mesmo submeteu. Peça a outro utilizador para rever.', 'danger')
        return redirect(url_for('pendentes'))

    novos_dados = json.loads(alteracao['dados_json'])
    dados_antigos = json.loads(alteracao['dados_antigos_json'])
    diffs = _diferencas(dados_antigos, novos_dados)
    _aplicar_alteracoes_ong(conn, alteracao['ong_id'], novos_dados)
    conn.execute('''
        UPDATE alteracoes_pendentes SET estado='Aprovado', revisto_por=?, revisto_em=?
        WHERE id=?
    ''', (session.get('utilizador'), datetime.now().strftime('%Y-%m-%d %H:%M:%S'), alteracao_id))
    if alteracao['ong_aprovacao'] == 'Aprovado':
        # Estava em revisão (ou sinalizada) — a edição foi validada, volta a publicada.
        conn.execute('''
            UPDATE ongs SET fase_workflow='Publicada', sinalizado_por=NULL,
                sinalizado_em=NULL, sinalizado_motivo=NULL WHERE id=?
        ''', (alteracao['ong_id'],))
    if diffs:
        auditoria.registar_diffs_por_campo(conn, alteracao['ong_id'], 'aprovar_edicao', diffs,
                                            session.get('utilizador'), request.remote_addr, alteracao['ong_nome'])
    conn.commit()
    conn.close()
    flash('Alteração validada e aplicada com sucesso.', 'success')
    return redirect(request.referrer or url_for('pendentes'))


@app.route('/alteracao/<int:alteracao_id>/rejeitar', methods=['POST'])
@login_obrigatorio
@requer_permissao('aprovar')
def rejeitar_edicao(alteracao_id):
    motivo = request.form.get('motivo', '').strip() or 'Sem motivo indicado'
    conn = get_connection()
    conn.execute('BEGIN IMMEDIATE')  # serializa: duas pessoas a decidir o mesmo registo em simultâneo
    alteracao = conn.execute('''
        SELECT ap.*, o.provincia AS ong_provincia, o.nome AS ong_nome, o.aprovacao AS ong_aprovacao
        FROM alteracoes_pendentes ap
        JOIN ongs o ON o.id = ap.ong_id
        WHERE ap.id = ? AND ap.estado = 'Pendente'
    ''', (alteracao_id,)).fetchone()
    if not alteracao:
        conn.close()
        flash('Esta alteração já foi tratada ou não existe.', 'warning')
        return redirect(url_for('pendentes'))

    escopo_provincia = provincia_sessao()
    if escopo_provincia and alteracao['ong_provincia'] != escopo_provincia:
        conn.close()
        flash('Esta ONG está fora da sua província de gestão.', 'danger')
        return redirect(url_for('pendentes'))

    if not perfis.pode_aprovar_registo(session.get('utilizador'), alteracao['solicitado_por']):
        conn.close()
        flash('Não pode rejeitar uma edição que você mesmo submeteu. Peça a outro utilizador para rever.', 'danger')
        return redirect(url_for('pendentes'))

    conn.execute('''
        UPDATE alteracoes_pendentes SET estado='Rejeitado', motivo_rejeicao=?, revisto_por=?, revisto_em=?
        WHERE id=? AND estado='Pendente'
    ''', (motivo, session.get('utilizador'), datetime.now().strftime('%Y-%m-%d %H:%M:%S'), alteracao_id))
    if alteracao['ong_aprovacao'] == 'Aprovado':
        conn.execute('''
            UPDATE ongs SET fase_workflow='Publicada', sinalizado_por=NULL,
                sinalizado_em=NULL, sinalizado_motivo=NULL WHERE id=?
        ''', (alteracao['ong_id'],))
    auditoria.registar(conn, 'rejeitar_edicao',
                        f'{session.get("utilizador")} rejeitou uma edição da ONG "{alteracao["ong_nome"]}" — motivo: {motivo}',
                        utilizador=session.get('utilizador'), ip=request.remote_addr, ong_id=alteracao['ong_id'],
                        detalhes={'motivo': motivo})
    conn.commit()
    conn.close()
    flash(f'Alteração rejeitada. A ONG mantém os dados anteriores. Motivo: {motivo}', 'danger')
    return redirect(request.referrer or url_for('pendentes'))


@app.route('/sector/<path:nome_area>')
def sector(nome_area):
    if nome_area not in ESTRUTURA_AREAS_TEMATICAS:
        flash(f'Área temática "{nome_area}" não encontrada.', 'warning')
        return redirect(url_for('dashboard'))

    conn = get_connection()

    provincia_filtro = request.args.get('provincia', '').strip()
    params_prov = [provincia_filtro] if provincia_filtro else []
    join_prov = 'JOIN ong_provincias opf ON opf.ong_id = o.id' if provincia_filtro else ''
    cond_prov = 'AND opf.provincia = ?' if provincia_filtro else ''

    ramificacoes_da_area = list(ESTRUTURA_AREAS_TEMATICAS[nome_area].keys())

    # Para cada ramificação, buscar as ONGs que nela operam
    dados_sector = []
    for nome_ramificacao in ramificacoes_da_area:
        ongs = conn.execute(f'''
            SELECT DISTINCT o.id, o.nome, o.natureza, o.origem, o.provincia, o.estado,
                            o.distritos_texto, o.area_intervencao
            FROM ongs o
            JOIN ong_ramificacoes orf ON orf.ong_id = o.id
            JOIN ramificacoes r ON r.id = orf.ramificacao_id
            {join_prov}
            WHERE r.nome = ? AND o.aprovacao = 'Aprovado' {cond_prov}
            ORDER BY o.nome
        ''', [nome_ramificacao] + params_prov).fetchall()

        dados_sector.append({
            'ramificacao': nome_ramificacao,
            'ongs': ongs,
            'total': len(ongs),
        })

    total_geral = conn.execute(f'''
        SELECT COUNT(DISTINCT o.id) FROM ongs o
        JOIN ong_areas oa ON oa.ong_id = o.id
        JOIN areas a ON a.id = oa.area_id
        {join_prov}
        WHERE a.nome = ? AND o.aprovacao = 'Aprovado' {cond_prov}
    ''', [nome_area] + params_prov).fetchone()[0]

    conn.close()

    return render_template('sector.html',
                            nome_area=nome_area,
                            dados_sector=dados_sector,
                            total_geral=total_geral,
                            provincias=PROVINCIAS,
                            provincia_filtro=provincia_filtro)


@app.route('/ong/<int:ong_id>')
def detalhe(ong_id):
    conn = get_connection()
    ong = conn.execute('SELECT * FROM ongs WHERE id = ?', (ong_id,)).fetchone()
    if not ong:
        conn.close()
        flash('ONG não encontrada.', 'warning')
        return redirect(url_for('index'))

    # Registos pendentes, rejeitados ou rascunhos NÃO são públicos: só utilizadores
    # autenticados (e, para rascunhos, o autor ou o Super Admin; e respeitando a
    # província do Gestor Provincial). Para os restantes, é como se não existissem.
    if ong['aprovacao'] != 'Aprovado' or ong['rascunho']:
        _esc = provincia_sessao()
        if (not e_admin()
                or (ong['rascunho'] and ong['criado_por'] != session.get('utilizador') and not e_super_admin())
                or (_esc and ong['provincia'] != _esc)):
            conn.close()
            abort(404)

    distritos = conn.execute('''
        SELECT d.nome FROM ong_distritos od
        JOIN distritos d ON d.id = od.distrito_id
        WHERE od.ong_id = ? ORDER BY d.nome
    ''', (ong_id,)).fetchall()

    areas = conn.execute('''
        SELECT a.nome FROM ong_areas oa
        JOIN areas a ON a.id = oa.area_id
        WHERE oa.ong_id = ? ORDER BY a.nome
    ''', (ong_id,)).fetchall()

    ramificacoes = conn.execute('''
        SELECT r.nome FROM ong_ramificacoes orf
        JOIN ramificacoes r ON r.id = orf.ramificacao_id
        WHERE orf.ong_id = ? ORDER BY r.nome
    ''', (ong_id,)).fetchall()

    provincias_ong = obter_provincias_da_ong(conn, ong_id) or ([ong['provincia']] if ong['provincia'] else [])

    alteracao_pendente = None
    diffs_pendentes = None
    if e_admin():
        alteracao_pendente = conn.execute('''
            SELECT * FROM alteracoes_pendentes WHERE ong_id = ? AND estado = 'Pendente'
            ORDER BY solicitado_em DESC LIMIT 1
        ''', (ong_id,)).fetchone()
        if alteracao_pendente:
            diffs_pendentes = _diferencas(json.loads(alteracao_pendente['dados_antigos_json']),
                                           json.loads(alteracao_pendente['dados_json']))

    historico = auditoria.obter_historico_ong(conn, ong_id) if perfis.tem_permissao(
        perfil_sessao() or ('super_admin' if e_super_admin() else ('admin' if e_admin() else '')), 'ver_auditoria'
    ) else []

    conn.close()
    return render_template('detalhe.html', ong=ong, distritos=distritos, areas=areas,
                            ramificacoes=ramificacoes, provincias_ong=provincias_ong,
                            alteracao_pendente=alteracao_pendente, diffs_pendentes=diffs_pendentes,
                            historico=historico)


CAMPOS_OBRIGATORIOS_LABELS = {
    'nome': 'Nome da organização',
    'natureza': 'Natureza',
    'origem': 'Origem',
    'provincias': 'Província(s) de actuação',
    'area_intervencao': 'Área/s Temática/s',
}


def nome_ja_registado(conn, nome, excluir_id=None):
    """Devolve a ONG (id, nome) que já usa este nome — comparação sem acentos,
    maiúsculas, hífens e texto entre parênteses. ONGs rejeitadas não contam."""
    from reconciliar_duplicados import normalizar_nome
    # Bloqueia a escrita ANTES de verificar: duas pessoas a registar o mesmo nome
    # no mesmo instante ficam em fila (a segunda vê a primeira e é recusada).
    if not conn.in_transaction:
        conn.execute('BEGIN IMMEDIATE')
    chave = normalizar_nome(nome or '')
    if not chave:
        return None
    for r in conn.execute("SELECT id, nome FROM ongs WHERE COALESCE(aprovacao, '') != 'Rejeitado'"):
        if excluir_id and r['id'] == excluir_id:
            continue
        if normalizar_nome(r['nome']) == chave:
            return r
    return None


def _validar_campos_obrigatorios(nome, natureza=None, origem=None, provincias=None, area_intervencao=None):
    """Requisito 07.10.2026: apenas o nome da organização é obrigatório.
    Natureza, origem, província(s), distrito(s) e áreas são opcionais."""
    erros = []
    if not nome:
        erros.append(CAMPOS_OBRIGATORIOS_LABELS['nome'])
    return erros


@app.route('/ong/novo', methods=['GET', 'POST'])
@login_obrigatorio
@requer_permissao('criar')
def novo():
    conn = get_connection()
    escopo_provincia = provincia_sessao()
    if request.method == 'POST':
        acao = request.form.get('acao', 'submeter')
        dados = _dados_formulario_ong(request.form)
        criado_por = session.get('utilizador')

        repetida = nome_ja_registado(conn, dados['nome'])
        if repetida:
            flash(f'Já existe uma ONG registada com o nome "{repetida["nome"]}" (n.º {repetida["id"]}). '
                  'Não é possível registar duas ONGs com o mesmo nome — edite a existente.', 'danger')
            conn.close()
            return render_template('formulario.html', ong=None, provincias=PROVINCIAS,
                                    provincias_ong=dados['provincias'], distritos_ong=dados['distritos_lista'])

        logo_url, erro_logo = processar_upload_logo(request.files.get('logo'))
        if erro_logo:
            flash(erro_logo, 'danger')
            conn.close()
            return render_template('formulario.html', ong=None, provincias=PROVINCIAS, provincias_ong=dados['provincias'], distritos_ong=dados['distritos_lista'])
        if logo_url:
            dados['logo_url'] = logo_url

        if acao == 'rascunho':
            # Rascunho: só o nome é obrigatório. NÃO sincroniza as tabelas de
            # província/área/natureza — assim nunca aparece em nenhuma
            # listagem, dashboard ou na API, mesmo que já tenha campos
            # preenchidos (essas tabelas é que alimentam essas contagens).
            if not dados['nome']:
                flash('Indique pelo menos o nome para guardar um rascunho.', 'danger')
            else:
                cur = conn.execute(f'''
                    INSERT INTO ongs ({", ".join(CAMPOS_EDITAVEIS)}, aprovacao, criado_por, rascunho, fase_workflow)
                    VALUES ({", ".join(["?"] * len(CAMPOS_EDITAVEIS))}, NULL, ?, 1, 'Rascunho')
                ''', tuple(dados.get(c) for c in CAMPOS_EDITAVEIS) + (criado_por,))
                auditoria.registar(conn, 'guardar_rascunho', f'{criado_por} guardou um rascunho: "{dados["nome"]}"',
                                    utilizador=criado_por, ip=request.remote_addr, ong_id=cur.lastrowid)
                conn.commit()
                conn.close()
                flash('Rascunho guardado. Pode continuar mais tarde em "Os meus rascunhos".', 'info')
                return redirect(url_for('rascunhos'))
            conn.close()
            return render_template('formulario.html', ong=None, provincias=PROVINCIAS, provincias_ong=[])

        erros = _validar_campos_obrigatorios(dados['nome'], dados['natureza'], dados['origem'],
                                              dados['provincias'], dados['area_intervencao'])
        if escopo_provincia and dados['provincias'] and any(p != escopo_provincia for p in dados['provincias']):
            erros = list(erros) + [f'só pode registar ONGs em {escopo_provincia}']
        if erros:
            flash('Preencha os campos obrigatórios: ' + ', '.join(erros) + '.', 'danger')
        else:
            aprovacao = 'Aprovado' if e_super_admin() else 'Pendente'
            fase_workflow = 'Publicada' if aprovacao == 'Aprovado' else 'Submetida'
            cur = conn.execute(f'''
                INSERT INTO ongs ({", ".join(CAMPOS_EDITAVEIS)}, aprovacao, criado_por, rascunho, fase_workflow)
                VALUES ({", ".join(["?"] * len(CAMPOS_EDITAVEIS))}, ?, ?, 0, ?)
            ''', tuple(dados.get(c) for c in CAMPOS_EDITAVEIS) + (aprovacao, criado_por, fase_workflow))
            sincronizar_tags(conn, cur.lastrowid, dados['distritos_texto'], dados['area_intervencao'], _prov_unica(dados), dados.get('distritos_lista'))
            sincronizar_provincias(conn, cur.lastrowid, dados['provincias'])
            sincronizar_naturezas(conn, cur.lastrowid, dados['natureza'])
            estado_txt = 'aprovado automaticamente' if aprovacao == 'Aprovado' else 'pendente de aprovação'
            auditoria.registar(conn, 'criar_ong', f'{criado_por} registou a ONG "{dados["nome"]}" ({estado_txt})',
                                utilizador=criado_por, ip=request.remote_addr, ong_id=cur.lastrowid)
            conn.commit()
            conn.close()
            if aprovacao == 'Pendente':
                flash('ONG registada e enviada para aprovação do Super Administrador.', 'warning')
            else:
                flash('ONG registada e aprovada com sucesso.', 'success')
            return redirect(url_for('index'))
    conn.close()
    return render_template('formulario.html', ong=None, provincias=PROVINCIAS, provincias_ong=[])


@app.route('/ong/<int:ong_id>/editar', methods=['GET', 'POST'])
@login_obrigatorio
@requer_permissao('editar')
def editar(ong_id):
    conn = get_connection()
    ong = conn.execute('SELECT * FROM ongs WHERE id = ?', (ong_id,)).fetchone()
    if not ong:
        conn.close()
        flash('ONG não encontrada.', 'warning')
        return redirect(url_for('index'))

    # Um rascunho só pode ser editado por quem o criou (ou pelo Super Admin)
    # — é trabalho privado, ainda não submetido a ninguém.
    if ong['rascunho'] and ong['criado_por'] != session.get('utilizador') and not e_super_admin():
        conn.close()
        flash('Este rascunho pertence a outro utilizador.', 'danger')
        return redirect(url_for('rascunhos'))

    escopo_provincia = provincia_sessao()
    if not ong['rascunho'] and escopo_provincia and ong['provincia'] != escopo_provincia:
        conn.close()
        flash('Esta ONG está fora da sua província de gestão.', 'danger')
        return redirect(url_for('index'))

    if request.method == 'POST':
        acao = request.form.get('acao', 'submeter')
        novos_dados = _dados_formulario_ong(request.form)

        repetida = nome_ja_registado(conn, novos_dados['nome'], excluir_id=ong_id)
        if repetida:
            flash(f'Já existe outra ONG com o nome "{repetida["nome"]}" (n.º {repetida["id"]}). '
                  'Escolha um nome diferente.', 'danger')
            conn.close()
            return render_template('formulario.html', ong=ong, provincias=PROVINCIAS,
                                    provincias_ong=novos_dados['provincias'],
                                    distritos_ong=novos_dados['distritos_lista'])

        logo_url, erro_logo = processar_upload_logo(request.files.get('logo'), logo_atual=ong['logo_url'])
        if erro_logo:
            flash(erro_logo, 'danger')
            conn.close()
            return render_template('formulario.html', ong=ong, provincias=PROVINCIAS,
                                    provincias_ong=novos_dados['provincias'],
                                    distritos_ong=novos_dados['distritos_lista'])
        novos_dados['logo_url'] = logo_url

        if ong['rascunho'] and acao == 'rascunho':
            # Continua como rascunho: grava os campos, sem validação nem
            # sincronização das tabelas de província/área/natureza.
            conn.execute(f'''
                UPDATE ongs SET {", ".join(f"{c}=?" for c in CAMPOS_EDITAVEIS)} WHERE id=?
            ''', tuple(novos_dados.get(c) for c in CAMPOS_EDITAVEIS) + (ong_id,))
            conn.commit()
            conn.close()
            flash('Rascunho actualizado.', 'info')
            return redirect(url_for('rascunhos'))

        erros = _validar_campos_obrigatorios(novos_dados['nome'], novos_dados['natureza'],
                                              novos_dados['origem'], novos_dados['provincias'],
                                              novos_dados['area_intervencao'])
        if escopo_provincia and novos_dados['provincias'] and any(p != escopo_provincia for p in novos_dados['provincias']):
            erros = list(erros) + [f'só pode manter esta ONG em {escopo_provincia}']
        if erros:
            flash('Preencha os campos obrigatórios: ' + ', '.join(erros) + '.', 'danger')
            conn.close()
            return render_template('formulario.html', ong=ong, provincias=PROVINCIAS,
                                    provincias_ong=novos_dados['provincias'],
                                    distritos_ong=novos_dados['distritos_lista'])

        if ong['rascunho'] and acao == 'submeter':
            # Rascunho -> submissão real: só agora entra nas tabelas de
            # província/área/natureza e passa a contar em todo o lado.
            aprovacao = 'Aprovado' if e_super_admin() else 'Pendente'
            fase_workflow = 'Publicada' if aprovacao == 'Aprovado' else 'Submetida'
            conn.execute(f'''
                UPDATE ongs SET {", ".join(f"{c}=?" for c in CAMPOS_EDITAVEIS)},
                    aprovacao=?, rascunho=0, fase_workflow=? WHERE id=?
            ''', tuple(novos_dados.get(c) for c in CAMPOS_EDITAVEIS) + (aprovacao, fase_workflow, ong_id))
            sincronizar_tags(conn, ong_id, novos_dados['distritos_texto'], novos_dados['area_intervencao'], _prov_unica(novos_dados), novos_dados.get('distritos_lista'))
            sincronizar_provincias(conn, ong_id, novos_dados['provincias'])
            sincronizar_naturezas(conn, ong_id, novos_dados['natureza'])
            auditoria.registar(conn, 'submeter_rascunho',
                                f'{session.get("utilizador")} submeteu o rascunho "{novos_dados["nome"]}"',
                                utilizador=session.get('utilizador'), ip=request.remote_addr, ong_id=ong_id)
            conn.commit()
            conn.close()
            flash('Rascunho submetido com sucesso.', 'success')
            return redirect(url_for('index'))

        if e_super_admin():
            # O Super Administrador tem autoridade para validar as suas
            # próprias alterações — entram em vigor de imediato.
            dados_antigos = _dados_atuais_da_ong(conn, ong)
            diffs = _diferencas(dados_antigos, novos_dados)
            _aplicar_alteracoes_ong(conn, ong_id, novos_dados)
            conn.execute("DELETE FROM alteracoes_pendentes WHERE ong_id = ? AND estado = 'Pendente'", (ong_id,))
            if ong['fase_workflow'] in ('Necessita Actualização', 'Em Revisão'):
                conn.execute('''
                    UPDATE ongs SET fase_workflow='Publicada', sinalizado_por=NULL,
                        sinalizado_em=NULL, sinalizado_motivo=NULL WHERE id=?
                ''', (ong_id,))
            if diffs:
                auditoria.registar_diffs_por_campo(conn, ong_id, 'editar_ong', diffs,
                                                    session.get('utilizador'), request.remote_addr, ong['nome'])
            conn.commit()
            conn.close()
            flash('ONG atualizada com sucesso.', 'success')
            return redirect(url_for('detalhe', ong_id=ong_id))

        # Qualquer outro perfil: a alteração fica em espera até alguém com
        # permissão de aprovar (e que não tenha sido quem submeteu) a validar.
        dados_antigos = _dados_atuais_da_ong(conn, ong)
        diffs = _diferencas(dados_antigos, novos_dados)
        if not diffs:
            conn.close()
            flash('Não há alterações para submeter.', 'info')
            return redirect(url_for('detalhe', ong_id=ong_id))

        conn.execute("DELETE FROM alteracoes_pendentes WHERE ong_id = ? AND estado = 'Pendente'", (ong_id,))
        conn.execute('''
            INSERT INTO alteracoes_pendentes (ong_id, dados_json, dados_antigos_json, solicitado_por, solicitado_em, estado)
            VALUES (?, ?, ?, ?, ?, 'Pendente')
        ''', (ong_id, json.dumps(novos_dados, ensure_ascii=False), json.dumps(dados_antigos, ensure_ascii=False),
              session.get('utilizador'), datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        if ong['aprovacao'] == 'Aprovado':
            # Uma ONG já publicada que recebe uma edição entra em revisão —
            # continua "Aprovada" (visível e contabilizada), só o sub-estado
            # interno muda, até a edição ser aprovada ou rejeitada.
            conn.execute("UPDATE ongs SET fase_workflow='Em Revisão' WHERE id=?", (ong_id,))
        campos_alterados = ', '.join(d['rotulo'] for d in diffs)
        auditoria.registar(conn, 'submeter_edicao',
                            f'{session.get("utilizador")} submeteu uma edição à ONG "{ong["nome"]}" '
                            f'({len(diffs)} campo(s): {campos_alterados}) — aguarda aprovação',
                            utilizador=session.get('utilizador'), ip=request.remote_addr, ong_id=ong_id,
                            detalhes=diffs)
        conn.commit()
        conn.close()
        flash('Alteração enviada para validação do Super Administrador. A ONG mantém os dados anteriores até lá ser aprovada.', 'warning')
        return redirect(url_for('detalhe', ong_id=ong_id))

    provincias_ong = obter_provincias_da_ong(conn, ong_id) or ([ong['provincia']] if ong['provincia'] else [])
    distritos_ong = _distritos_da_ong(conn, ong_id)
    conn.close()
    return render_template('formulario.html', ong=ong, provincias=PROVINCIAS, provincias_ong=provincias_ong,
                            distritos_ong=distritos_ong)


@app.route('/ong/<int:ong_id>/eliminar', methods=['POST'])
@super_admin_obrigatorio
def eliminar(ong_id):
    conn = get_connection()
    conn.execute('BEGIN IMMEDIATE')  # serializa: duas pessoas a decidir o mesmo registo em simultâneo
    ong = conn.execute('SELECT nome FROM ongs WHERE id = ?', (ong_id,)).fetchone()
    nome_ong = ong['nome'] if ong else f'#{ong_id}'
    conn.execute('DELETE FROM ongs WHERE id = ?', (ong_id,))
    auditoria.registar(conn, 'eliminar_ong', f'{session.get("utilizador")} eliminou a ONG "{nome_ong}"',
                        utilizador=session.get('utilizador'), ip=request.remote_addr, ong_id=None,
                        detalhes={'ong_id_eliminado': ong_id, 'nome': nome_ong})
    conn.commit()
    conn.close()
    flash('ONG eliminada.', 'info')
    return redirect(url_for('index'))


EMAIL_RE = re.compile(r'^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$')


# ─── GESTÃO DE UTILIZADORES ────────────────────────────────────────────────────
@app.route('/utilizadores')
@login_obrigatorio
@requer_permissao('gerir_utilizadores')
def utilizadores():
    conn = get_connection()
    lista = conn.execute('SELECT * FROM utilizadores ORDER BY criado_em DESC').fetchall()
    conn.close()
    perfil_actual = perfil_sessao() or ('super_admin' if e_super_admin() else 'admin')
    return render_template('utilizadores.html', utilizadores=lista,
                            perfis_atribuiveis=sorted(perfis.perfis_atribuiveis_por(perfil_actual)),
                            perfil_atual=perfil_actual,
                            provincias=PROVINCIAS)


@app.route('/utilizadores/novo', methods=['POST'])
@login_obrigatorio
@requer_permissao('gerir_utilizadores')
def novo_utilizador():
    perfil_actual = perfil_sessao() or ('super_admin' if e_super_admin() else 'admin')
    email = request.form.get('email', '').strip().lower()
    username = email
    nome_completo = request.form.get('nome_completo', '').strip()
    senha = request.form.get('senha', '')
    perfil_novo = request.form.get('perfil', '').strip()
    provincia_novo = request.form.get('provincia', '').strip() or None

    if not email or not senha or not perfil_novo:
        flash('Preencha e-mail, palavra-passe e perfil.', 'danger')
        return redirect(url_for('utilizadores'))
    if not EMAIL_RE.match(email):
        flash('Indique um e-mail válido (ex.: nome@dominio.gov.mz).', 'danger')
        return redirect(url_for('utilizadores'))

    forte, motivo = seguranca.senha_e_forte(senha)
    if not forte:
        flash(motivo, 'danger')
        return redirect(url_for('utilizadores'))

    if perfil_novo not in perfis.perfis_atribuiveis_por(perfil_actual):
        flash('O seu perfil não tem autorização para criar uma conta com esse perfil.', 'danger')
        return redirect(url_for('utilizadores'))

    if perfil_novo == 'gestor_provincial' and not provincia_novo:
        flash('Um Gestor Provincial tem de ter uma província atribuída.', 'danger')
        return redirect(url_for('utilizadores'))

    conn = get_connection()
    existe = conn.execute('SELECT id FROM utilizadores WHERE username = ? OR lower(email) = ?', (username, email)).fetchone()
    if existe:
        conn.close()
        flash('Já existe uma conta com esse e-mail.', 'danger')
        return redirect(url_for('utilizadores'))
    if perfil_novo == 'gestor_provincial':
        ja_gestor = conn.execute("SELECT username FROM utilizadores WHERE perfil = 'gestor_provincial' AND provincia = ?",
                                  (provincia_novo,)).fetchone()
        if ja_gestor:
            conn.close()
            flash(f'A província {provincia_novo} já tem um Gestor Provincial ({ja_gestor["username"]}). '
                  'Desactive ou edite essa conta em vez de criar outra.', 'danger')
            return redirect(url_for('utilizadores'))

    conn.execute('''
        INSERT INTO utilizadores (username, email, nome_completo, password_hash, perfil, provincia, criado_por, deve_mudar_senha)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1)
    ''', (username, email, nome_completo, generate_password_hash(senha), perfil_novo,
          provincia_novo if perfil_novo == 'gestor_provincial' else None,
          session.get('utilizador')))
    auditoria.registar(conn, 'criar_utilizador',
                        f'{session.get("utilizador")} criou a conta "{username}" como {perfis.ROTULOS_PERFIS.get(perfil_novo, perfil_novo)}',
                        utilizador=session.get('utilizador'), ip=request.remote_addr,
                        detalhes={'novo_utilizador': username, 'perfil': perfil_novo, 'provincia': provincia_novo})
    conn.commit()
    conn.close()
    flash(f'Utilizador "{username}" criado como {perfis.ROTULOS_PERFIS.get(perfil_novo, perfil_novo)}.', 'success')
    return redirect(url_for('utilizadores'))


@app.route('/utilizadores/gestores-provinciais', methods=['POST'])
@login_obrigatorio
@requer_permissao('gerir_utilizadores')
def criar_gestores_provinciais():
    perfil_actual = perfil_sessao() or ('super_admin' if e_super_admin() else 'admin')
    if 'gestor_provincial' not in perfis.perfis_atribuiveis_por(perfil_actual):
        abort(403)
    dominio = (request.form.get('dominio') or contas_iniciais.DOMINIO_PADRAO).strip().lower().lstrip('@')
    if not re.match(r'^[a-z0-9.\-]+\.[a-z]{2,}$', dominio):
        flash('Domínio de e-mail inválido.', 'danger')
        return redirect(url_for('utilizadores'))
    conn = get_connection()
    criadas, ignoradas = contas_iniciais.criar_gestores_provinciais(conn, dominio, session.get('utilizador'))
    if criadas:
        auditoria.registar(conn, 'criar_utilizador',
                            f'{session.get("utilizador")} criou {len(criadas)} conta(s) de Gestor Provincial',
                            utilizador=session.get('utilizador'), ip=request.remote_addr,
                            detalhes={'provincias': [c['provincia'] for c in criadas]})
    conn.commit()
    conn.close()
    return render_template('gestores_criados.html', criadas=criadas, ignoradas=ignoradas)


def _pode_gerir_conta(alvo):
    """Quem pode repor senha/2FA, mudar e-mail ou desactivar uma conta: apenas
    perfis ESTRITAMENTE abaixo (Super Admin gere todos; Admin gere gestores,
    operadores e consulta — nunca outro Admin nem o Super Admin)."""
    perfil_actual = perfil_sessao() or ('super_admin' if e_super_admin() else 'admin')
    return alvo['perfil'] in perfis.perfis_atribuiveis_por(perfil_actual)


def _garantir_super_admin_inicial():
    """Cria o primeiro Super Administrador a partir de SGIONGS_BOOTSTRAP_EMAIL /
    SGIONGS_BOOTSTRAP_PASSWORD, se ainda não existir nenhum na base de dados.
    Obriga a mudar a senha no primeiro acesso."""
    if not (BOOTSTRAP_EMAIL and BOOTSTRAP_PASSWORD):
        return
    conn = get_connection()
    try:
        existe = conn.execute("SELECT 1 FROM utilizadores WHERE perfil = 'super_admin' AND activo = 1").fetchone()
        if not existe and EMAIL_RE.match(BOOTSTRAP_EMAIL):
            conn.execute('''INSERT INTO utilizadores (username, email, nome_completo, password_hash, perfil, activo, deve_mudar_senha, criado_por)
                            VALUES (?, ?, ?, ?, 'super_admin', 1, 1, 'arranque')''',
                         (BOOTSTRAP_EMAIL, BOOTSTRAP_EMAIL, 'Super Administrador', generate_password_hash(BOOTSTRAP_PASSWORD)))
            auditoria.registar(conn, 'criar_utilizador', f'Super Administrador inicial criado ({BOOTSTRAP_EMAIL})', utilizador='arranque')
            conn.commit()
    finally:
        conn.close()


@app.route('/utilizadores/<int:utilizador_id>/repor-senha', methods=['POST'])
@login_obrigatorio
@requer_permissao('gerir_utilizadores')
def repor_senha_utilizador(utilizador_id):
    conn = get_connection()
    alvo = conn.execute('SELECT * FROM utilizadores WHERE id = ?', (utilizador_id,)).fetchone()
    if not alvo or not _pode_gerir_conta(alvo):
        conn.close()
        flash('Conta não encontrada ou sem autorização para a gerir.', 'danger')
        return redirect(url_for('utilizadores'))
    nova = contas_iniciais.gerar_senha()
    conn.execute('UPDATE utilizadores SET password_hash = ?, deve_mudar_senha = 1 WHERE id = ?',
                 (generate_password_hash(nova), utilizador_id))
    login_guard.limpar_conta(conn, alvo['username'])  # desbloqueia a conta
    auditoria.registar(conn, 'alterar_senha', f'{session.get("utilizador")} repôs a palavra-passe de "{alvo["username"]}"',
                        utilizador=session.get('utilizador'), ip=request.remote_addr)
    conn.commit()
    conn.close()
    return render_template('gestores_criados.html', criadas=[{'provincia': alvo['provincia'] or alvo['perfil'],
                            'email': alvo['email'] or alvo['username'], 'senha': nova}], ignoradas=[], reposicao=True)


@app.route('/utilizadores/<int:utilizador_id>/repor-2fa', methods=['POST'])
@login_obrigatorio
@requer_permissao('gerir_utilizadores')
def repor_2fa_utilizador(utilizador_id):
    """Recuperação de conta: o utilizador perdeu o telemóvel/autenticador.
    Desliga o 2FA (e desbloqueia a conta); o utilizador volta a activá-lo em /conta."""
    conn = get_connection()
    alvo = conn.execute('SELECT * FROM utilizadores WHERE id = ?', (utilizador_id,)).fetchone()
    if not alvo or not _pode_gerir_conta(alvo):
        conn.close()
        flash('Conta não encontrada ou sem autorização para a gerir.', 'danger')
        return redirect(url_for('utilizadores'))
    conn.execute('UPDATE utilizadores SET totp_ativo = 0, totp_secret = NULL, totp_ultimo_passo = NULL WHERE id = ?', (utilizador_id,))
    conn.execute('DELETE FROM codigos_recuperacao_2fa WHERE utilizador_id = ?', (utilizador_id,))
    login_guard.limpar_conta(conn, alvo['username'])
    auditoria.registar(conn, 'desactivar_2fa', f'{session.get("utilizador")} repôs o 2FA de "{alvo["username"]}" (recuperação de conta)',
                        utilizador=session.get('utilizador'), ip=request.remote_addr)
    conn.commit()
    conn.close()
    flash(f'2FA de {alvo["username"]} desligado. A pessoa pode voltar a activá-lo em "A minha conta".', 'success')
    return redirect(url_for('utilizadores'))


@app.route('/utilizadores/<int:utilizador_id>/email', methods=['POST'])
@login_obrigatorio
@requer_permissao('gerir_utilizadores')
def alterar_email_utilizador(utilizador_id):
    email = request.form.get('email', '').strip().lower()
    if not EMAIL_RE.match(email):
        flash('Indique um e-mail válido.', 'danger')
        return redirect(url_for('utilizadores'))
    conn = get_connection()
    alvo = conn.execute('SELECT * FROM utilizadores WHERE id = ?', (utilizador_id,)).fetchone()
    if not alvo or not _pode_gerir_conta(alvo):
        conn.close()
        flash('Conta não encontrada ou sem autorização para a gerir.', 'danger')
        return redirect(url_for('utilizadores'))
    outro = conn.execute('SELECT id FROM utilizadores WHERE (lower(email) = ? OR username = ?) AND id != ?',
                         (email, email, utilizador_id)).fetchone()
    if outro:
        conn.close()
        flash('Esse e-mail já pertence a outra conta.', 'danger')
        return redirect(url_for('utilizadores'))
    conn.execute('UPDATE utilizadores SET email = ?, username = ? WHERE id = ?', (email, email, utilizador_id))
    auditoria.registar(conn, 'editar_utilizador', f'{session.get("utilizador")} alterou o e-mail de "{alvo["username"]}" para "{email}"',
                        utilizador=session.get('utilizador'), ip=request.remote_addr)
    conn.commit()
    conn.close()
    flash('E-mail actualizado — é também o novo nome de entrada.', 'success')
    return redirect(url_for('utilizadores'))


@app.route('/utilizadores/<int:utilizador_id>/desactivar', methods=['POST'])
@login_obrigatorio
@requer_permissao('gerir_utilizadores')
def desactivar_utilizador(utilizador_id):
    conn = get_connection()
    alvo = conn.execute('SELECT * FROM utilizadores WHERE id = ?', (utilizador_id,)).fetchone()
    if not alvo:
        conn.close()
        flash('Utilizador não encontrado.', 'warning')
        return redirect(url_for('utilizadores'))

    if not _pode_gerir_conta(alvo):
        conn.close()
        flash('O seu perfil não tem autorização para gerir esta conta.', 'danger')
        return redirect(url_for('utilizadores'))

    if utilizador_id == session.get('utilizador_id'):
        conn.close()
        flash('Não pode desactivar a sua própria conta.', 'danger')
        return redirect(url_for('utilizadores'))

    novo_estado = 0 if alvo['activo'] else 1
    conn.execute('UPDATE utilizadores SET activo = ? WHERE id = ?', (novo_estado, utilizador_id))
    accao = 'reactivar_utilizador' if novo_estado else 'desactivar_utilizador'
    auditoria.registar(conn, accao,
                        f'{session.get("utilizador")} {"reactivou" if novo_estado else "desactivou"} a conta "{alvo["username"]}"',
                        utilizador=session.get('utilizador'), ip=request.remote_addr,
                        detalhes={'alvo': alvo['username']})
    conn.commit()
    conn.close()
    flash('Utilizador ' + ('reactivado.' if novo_estado else 'desactivado.'), 'info')
    return redirect(url_for('utilizadores'))


@app.route('/auditoria')
@login_obrigatorio
@requer_permissao('ver_auditoria')
def auditoria_geral():
    utilizador_filtro = request.args.get('utilizador', '').strip() or None
    accao_filtro = request.args.get('accao', '').strip() or None
    escopo_provincia = provincia_sessao()

    conn = get_connection()
    entradas = auditoria.obter_historico_geral(conn, utilizador=utilizador_filtro, accao=accao_filtro,
                                                provincia=escopo_provincia)
    utilizadores_distintos = conn.execute(
        'SELECT DISTINCT utilizador FROM historico_auditoria WHERE utilizador IS NOT NULL ORDER BY utilizador'
    ).fetchall()
    conn.close()

    return render_template('auditoria.html', entradas=entradas,
                            utilizadores_distintos=[u['utilizador'] for u in utilizadores_distintos],
                            accoes=auditoria.ROTULOS_ACCOES,
                            utilizador_filtro=utilizador_filtro, accao_filtro=accao_filtro)


@app.route('/rascunhos')
@login_obrigatorio
@requer_permissao('criar')
def rascunhos():
    conn = get_connection()
    if e_super_admin():
        lista = conn.execute("SELECT * FROM ongs WHERE rascunho = 1 ORDER BY id DESC").fetchall()
    else:
        lista = conn.execute("SELECT * FROM ongs WHERE rascunho = 1 AND criado_por = ? ORDER BY id DESC",
                              (session.get('utilizador'),)).fetchall()
    conn.close()
    return render_template('rascunhos.html', rascunhos=lista)


@app.route('/rascunho/<int:ong_id>/eliminar', methods=['POST'])
@login_obrigatorio
@requer_permissao('criar')
def eliminar_rascunho(ong_id):
    conn = get_connection()
    rascunho = conn.execute('SELECT * FROM ongs WHERE id = ? AND rascunho = 1', (ong_id,)).fetchone()
    if not rascunho:
        conn.close()
        flash('Rascunho não encontrado.', 'warning')
        return redirect(url_for('rascunhos'))
    if rascunho['criado_por'] != session.get('utilizador') and not e_super_admin():
        conn.close()
        flash('Este rascunho pertence a outro utilizador.', 'danger')
        return redirect(url_for('rascunhos'))

    conn.execute('DELETE FROM ongs WHERE id = ?', (ong_id,))
    auditoria.registar(conn, 'eliminar_rascunho', f'{session.get("utilizador")} eliminou o rascunho "{rascunho["nome"]}"',
                        utilizador=session.get('utilizador'), ip=request.remote_addr)
    conn.commit()
    conn.close()
    flash('Rascunho eliminado.', 'info')
    return redirect(url_for('rascunhos'))


@app.route('/ong/<int:ong_id>/iniciar-analise', methods=['POST'])
@login_obrigatorio
@requer_permissao('aprovar')
def iniciar_analise(ong_id):
    conn = get_connection()
    ong = conn.execute("SELECT nome, provincia, aprovacao FROM ongs WHERE id = ?", (ong_id,)).fetchone()
    if not ong or ong['aprovacao'] != 'Pendente':
        conn.close()
        flash('Este registo não está pendente de aprovação.', 'warning')
        return redirect(url_for('pendentes'))

    escopo_provincia = provincia_sessao()
    if escopo_provincia and ong['provincia'] != escopo_provincia:
        conn.close()
        flash('Esta ONG está fora da sua província de gestão.', 'danger')
        return redirect(url_for('pendentes'))

    conn.execute('''
        UPDATE ongs SET fase_workflow='Em Análise', em_analise_por=?, em_analise_em=? WHERE id=?
    ''', (session.get('utilizador'), datetime.now().strftime('%Y-%m-%d %H:%M:%S'), ong_id))
    auditoria.registar(conn, 'iniciar_analise', f'{session.get("utilizador")} iniciou a análise da ONG "{ong["nome"]}"',
                        utilizador=session.get('utilizador'), ip=request.remote_addr, ong_id=ong_id)
    conn.commit()
    conn.close()
    flash('Marcado como em análise.', 'info')
    return redirect(url_for('pendentes'))


@app.route('/ong/<int:ong_id>/sinalizar-atualizacao', methods=['POST'])
@login_obrigatorio
@requer_permissao('aprovar')
def sinalizar_atualizacao(ong_id):
    motivo = request.form.get('motivo', '').strip()
    if not motivo:
        flash('Indique o motivo da sinalização.', 'danger')
        return redirect(url_for('detalhe', ong_id=ong_id))

    conn = get_connection()
    ong = conn.execute("SELECT nome, provincia, aprovacao FROM ongs WHERE id = ?", (ong_id,)).fetchone()
    if not ong or ong['aprovacao'] != 'Aprovado':
        conn.close()
        flash('Só é possível sinalizar registos já aprovados.', 'warning')
        return redirect(url_for('detalhe', ong_id=ong_id))

    escopo_provincia = provincia_sessao()
    if escopo_provincia and ong['provincia'] != escopo_provincia:
        conn.close()
        flash('Esta ONG está fora da sua província de gestão.', 'danger')
        return redirect(url_for('detalhe', ong_id=ong_id))

    conn.execute('''
        UPDATE ongs SET fase_workflow='Necessita Actualização', sinalizado_por=?, sinalizado_em=?, sinalizado_motivo=?
        WHERE id=?
    ''', (session.get('utilizador'), datetime.now().strftime('%Y-%m-%d %H:%M:%S'), motivo, ong_id))
    auditoria.registar(conn, 'sinalizar_atualizacao',
                        f'{session.get("utilizador")} sinalizou a ONG "{ong["nome"]}" para actualização — motivo: {motivo}',
                        utilizador=session.get('utilizador'), ip=request.remote_addr, ong_id=ong_id,
                        detalhes={'motivo': motivo})
    conn.commit()
    conn.close()
    flash('ONG sinalizada como necessitando actualização.', 'warning')
    return redirect(url_for('detalhe', ong_id=ong_id))


def _filtros_relatorio_do_pedido():
    filtros = {
        'provincia': request.args.get('provincia', '').strip(),
        'area_id': request.args.get('area_id', '').strip(),
        'distrito_id': request.args.get('distrito_id', '').strip(),
        'natureza': request.args.get('natureza', '').strip(),
        'origem': request.args.get('origem', '').strip(),
        'desde': request.args.get('desde', '').strip(),
        'ate': request.args.get('ate', '').strip(),
    }
    escopo_provincia = provincia_sessao()
    if escopo_provincia:
        filtros['provincia'] = escopo_provincia  # Gestor Provincial: relatório sempre limitado à sua província
    return {k: v for k, v in filtros.items() if v}


def _nome_ficheiro_relatorio(filtros, extensao):
    partes = ['relatorio_ongs']
    if filtros.get('provincia'):
        partes.append(filtros['provincia'].lower().replace(' ', '_'))
    partes.append(datetime.now().strftime('%Y%m%d'))
    return '_'.join(partes) + f'.{extensao}'


@app.route('/relatorios')
@login_obrigatorio
def relatorios_pagina():
    conn = get_connection()
    _, areas, _ = obter_listas_filtro(conn, None)
    conn.close()
    escopo_provincia = provincia_sessao()
    return render_template('relatorios.html', provincias=PROVINCIAS, areas=areas,
                            escopo_provincia=escopo_provincia)


@app.route('/relatorios/pdf')
@login_obrigatorio
def relatorio_pdf():
    filtros = _filtros_relatorio_do_pedido()
    conn = get_connection()
    contexto = None
    if filtros.get('provincia'):
        contexto = f'Província de {filtros["provincia"]}'
    conteudo = relatorios.gerar_pdf(conn, filtros, titulo_contexto=contexto)
    auditoria.registar(conn, 'gerar_relatorio', f'{session.get("utilizador")} gerou um relatório PDF',
                        utilizador=session.get('utilizador'), ip=request.remote_addr, detalhes=filtros)
    conn.commit()
    conn.close()
    return Response(conteudo, mimetype='application/pdf', headers={
        'Content-Disposition': f'attachment; filename="{_nome_ficheiro_relatorio(filtros, "pdf")}"'
    })


@app.route('/relatorios/excel')
@login_obrigatorio
def relatorio_excel():
    filtros = _filtros_relatorio_do_pedido()
    conn = get_connection()
    conteudo = relatorios.gerar_excel(conn, filtros)
    conn.close()
    return Response(conteudo, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     headers={'Content-Disposition': f'attachment; filename="{_nome_ficheiro_relatorio(filtros, "xlsx")}"'})


@app.route('/relatorios/csv')
@login_obrigatorio
def relatorio_csv():
    filtros = _filtros_relatorio_do_pedido()
    conn = get_connection()
    conteudo = relatorios.gerar_csv(conn, filtros)
    conn.close()
    return Response(conteudo, mimetype='text/csv',
                     headers={'Content-Disposition': f'attachment; filename="{_nome_ficheiro_relatorio(filtros, "csv")}"'})


@app.route('/conta')
@login_obrigatorio
def conta():
    utilizador_id = session.get('utilizador_id')
    linha = None
    if utilizador_id:
        conn = get_connection()
        linha = conn.execute('SELECT * FROM utilizadores WHERE id = ?', (utilizador_id,)).fetchone()
        restantes = seguranca.codigos_restantes(conn, utilizador_id) if linha and linha['totp_ativo'] else 0
        conn.close()
    else:
        restantes = 0
    obrigatorio = bool(EXIGIR_2FA_ADMIN and linha and linha['perfil'] in PERFIS_2FA_OBRIGATORIO)
    return render_template('conta.html', utilizador_db=linha, codigos_restantes=restantes, tfa_obrigatorio=obrigatorio)


@app.route('/conta/senha', methods=['POST'])
@login_obrigatorio
def alterar_propria_senha():
    utilizador_id = session.get('utilizador_id')
    if not utilizador_id:
        flash('As contas de arranque (variável de ambiente) não podem alterar a senha por aqui — '
              'peça a um Super Administrador para lhe criar uma conta própria em Utilizadores.', 'warning')
        return redirect(url_for('conta'))

    senha_actual = request.form.get('senha_actual', '')
    nova_senha = request.form.get('nova_senha', '')
    confirmar = request.form.get('confirmar_senha', '')

    conn = get_connection()
    linha = conn.execute('SELECT * FROM utilizadores WHERE id = ?', (utilizador_id,)).fetchone()
    if not linha or not check_password_hash(linha['password_hash'], senha_actual):
        conn.close()
        flash('Senha actual incorrecta.', 'danger')
        return redirect(url_for('conta'))

    if nova_senha != confirmar:
        conn.close()
        flash('A confirmação não coincide com a nova senha.', 'danger')
        return redirect(url_for('conta'))

    forte, motivo = seguranca.senha_e_forte(nova_senha)
    if not forte:
        conn.close()
        flash(motivo, 'danger')
        return redirect(url_for('conta'))

    conn.execute('UPDATE utilizadores SET password_hash = ?, senha_alterada_em = ?, deve_mudar_senha = 0 WHERE id = ?',
                 (generate_password_hash(nova_senha), datetime.now().strftime('%Y-%m-%d %H:%M:%S'), utilizador_id))
    session['deve_mudar_senha'] = False
    auditoria.registar(conn, 'alterar_senha', f'{session.get("utilizador")} alterou a própria senha',
                        utilizador=session.get('utilizador'), ip=request.remote_addr)
    conn.commit()
    conn.close()
    flash('Senha alterada com sucesso.', 'success')
    return redirect(url_for('conta'))


@app.route('/conta/2fa/configurar')
@login_obrigatorio
def configurar_2fa():
    utilizador_id = session.get('utilizador_id')
    if not utilizador_id:
        flash('2FA só está disponível para contas criadas em Utilizadores.', 'warning')
        return redirect(url_for('conta'))

    conn = get_connection()
    linha = conn.execute('SELECT * FROM utilizadores WHERE id = ?', (utilizador_id,)).fetchone()
    if linha['totp_ativo']:
        conn.close()
        flash('O 2FA já está activo nesta conta.', 'info')
        return redirect(url_for('conta'))

    # Gera (ou reaproveita) um segredo ainda por confirmar — só fica activo
    # depois de o próprio provar, na próxima rota, que o consegue ler.
    segredo = linha['totp_secret'] or seguranca.gerar_segredo_totp()
    conn.execute('UPDATE utilizadores SET totp_secret = ? WHERE id = ?', (segredo, utilizador_id))
    conn.commit()
    conn.close()

    uri = seguranca.uri_provisionamento(segredo, session.get('utilizador'))
    return render_template('configurar_2fa.html', segredo=segredo, uri=uri)


@app.route('/conta/2fa/qrcode.png')
@login_obrigatorio
def qrcode_2fa():
    utilizador_id = session.get('utilizador_id')
    if not utilizador_id:
        abort(404)
    conn = get_connection()
    linha = conn.execute('SELECT totp_secret FROM utilizadores WHERE id = ?', (utilizador_id,)).fetchone()
    conn.close()
    if not linha or not linha['totp_secret']:
        abort(404)
    uri = seguranca.uri_provisionamento(linha['totp_secret'], session.get('utilizador'))
    return Response(seguranca.gerar_qrcode_png(uri), mimetype='image/png')


@app.route('/conta/2fa/activar', methods=['POST'])
@login_obrigatorio
def activar_2fa():
    utilizador_id = session.get('utilizador_id')
    if not utilizador_id:
        return redirect(url_for('conta'))

    codigo = request.form.get('codigo', '').strip()
    conn = get_connection()
    linha = conn.execute('SELECT * FROM utilizadores WHERE id = ?', (utilizador_id,)).fetchone()

    passo = seguranca.passo_totp_valido(linha['totp_secret'], codigo)
    if passo is None:
        conn.close()
        flash('Código incorrecto. Tente novamente (o código muda a cada 30 segundos).', 'danger')
        return redirect(url_for('configurar_2fa'))

    conn.execute('UPDATE utilizadores SET totp_ativo = 1, totp_ultimo_passo = ? WHERE id = ?', (passo, utilizador_id))
    codigos = seguranca.gerar_codigos_recuperacao(conn, utilizador_id)
    auditoria.registar(conn, 'activar_2fa', f'{session.get("utilizador")} activou a verificação em duas etapas',
                        utilizador=session.get('utilizador'), ip=request.remote_addr)
    conn.commit()
    conn.close()
    session['deve_configurar_2fa'] = False
    flash('Verificação em duas etapas activada com sucesso.', 'success')
    return _sem_cache(render_template('codigos_recuperacao.html', codigos=codigos, novo=True))


@app.route('/conta/2fa/codigos', methods=['POST'])
@login_obrigatorio
def regenerar_codigos_2fa():
    """Gera novos códigos de recuperação (os antigos deixam de valer). Exige a senha actual."""
    utilizador_id = session.get('utilizador_id')
    conn = get_connection()
    linha = conn.execute('SELECT * FROM utilizadores WHERE id = ?', (utilizador_id,)).fetchone() if utilizador_id else None
    if not linha or not linha['totp_ativo'] or not check_password_hash(linha['password_hash'], request.form.get('senha_actual', '')):
        conn.close()
        flash('Senha incorrecta ou 2FA inactivo — não foram gerados códigos.', 'danger')
        return redirect(url_for('conta'))
    codigos = seguranca.gerar_codigos_recuperacao(conn, utilizador_id)
    auditoria.registar(conn, 'gerar_codigos_2fa', f'{session.get("utilizador")} gerou novos códigos de recuperação do 2FA',
                        utilizador=session.get('utilizador'), ip=request.remote_addr)
    conn.commit()
    conn.close()
    return _sem_cache(render_template('codigos_recuperacao.html', codigos=codigos, novo=False))


@app.route('/conta/2fa/desactivar', methods=['POST'])
@login_obrigatorio
def desactivar_2fa():
    utilizador_id = session.get('utilizador_id')
    if not utilizador_id:
        return redirect(url_for('conta'))

    senha_actual = request.form.get('senha_actual', '')
    conn = get_connection()
    linha = conn.execute('SELECT * FROM utilizadores WHERE id = ?', (utilizador_id,)).fetchone()
    if EXIGIR_2FA_ADMIN and linha and linha['perfil'] in PERFIS_2FA_OBRIGATORIO:
        conn.close()
        flash('O 2FA é obrigatório para o seu perfil e não pode ser desactivado.', 'warning')
        return redirect(url_for('conta'))
    if not linha or not check_password_hash(linha['password_hash'], senha_actual):
        conn.close()
        flash('Senha incorrecta — a desactivação do 2FA não foi confirmada.', 'danger')
        return redirect(url_for('conta'))

    conn.execute('UPDATE utilizadores SET totp_ativo = 0, totp_secret = NULL, totp_ultimo_passo = NULL WHERE id = ?', (utilizador_id,))
    conn.execute('DELETE FROM codigos_recuperacao_2fa WHERE utilizador_id = ?', (utilizador_id,))
    auditoria.registar(conn, 'desactivar_2fa', f'{session.get("utilizador")} desactivou a verificação em duas etapas',
                        utilizador=session.get('utilizador'), ip=request.remote_addr)
    conn.commit()
    conn.close()
    flash('Verificação em duas etapas desactivada.', 'warning')
    return redirect(url_for('conta'))



# ─── RECUPERAÇÃO DE SENHA POR E-MAIL ─────────────────────────────────────────
# Segurança: a resposta é SEMPRE a mesma (não revela se o e-mail existe); o token
# (256 bits) só fica guardado como hash, vale 30 min e uma única vez; pedidos são
# limitados por e-mail e por IP; o 2FA continua a ser exigido depois (a recuperação
# de senha nunca o contorna); cada passo fica na auditoria.
_MSG_RECUPERACAO = ('Se o e-mail corresponder a uma conta activa, enviámos uma ligação para definir uma nova senha '
                    '(válida durante 30 minutos). Verifique também o spam.')


@app.route('/recuperar-senha', methods=['GET', 'POST'])
def recuperar_senha():
    if not emails.disponivel():
        flash('A recuperação por e-mail não está configurada. Peça a um administrador para repor a sua senha.', 'info')
        return redirect(url_for('login'))
    if request.method == 'POST':
        ip = request.remote_addr
        email = (request.form.get('email') or '').strip().lower()[:200]
        conn = get_connection()
        chave = 'reset:' + email
        if login_guard.bloqueado(conn, ip, chave):
            conn.close()
            flash(_MSG_RECUPERACAO, 'info')           # mesma resposta: não denuncia o limite
            return redirect(url_for('login'))
        login_guard.registar_falha(conn, ip, chave)   # conta como pedido (limite 5 / 15 min por e-mail)
        linha = conn.execute('SELECT * FROM utilizadores WHERE lower(email) = ? AND activo = 1', (email,)).fetchone() if email else None
        if linha:
            token = seguranca.criar_token_reset(conn, linha['id'], ip)
            ligacao = emails.url_base(request.host_url) + url_for('redefinir_senha', token=token)
            auditoria.registar(conn, 'pedido_recuperacao_senha', f'Pedido de recuperação de senha para {linha["username"]}',
                                utilizador=linha['username'], ip=ip)
            conn.commit()
            emails.enviar(linha['email'], 'SGIONGs — recuperar a senha',
                          'Recebemos um pedido para definir uma nova senha da sua conta no SGIONGs.\n\n'
                          f'Abra esta ligação (válida durante 30 minutos, uso único):\n{ligacao}\n\n'
                          'Se não foi você, ignore esta mensagem — a sua senha não foi alterada.')
        else:
            conn.commit()
        conn.close()
        flash(_MSG_RECUPERACAO, 'info')
        return redirect(url_for('login'))
    return render_template('recuperar_senha.html')


@app.route('/recuperar-senha/<token>', methods=['GET', 'POST'])
def redefinir_senha(token):
    conn = get_connection()
    registo = seguranca.token_reset_valido(conn, token)
    if not registo:
        conn.close()
        flash('Esta ligação é inválida ou expirou. Peça uma nova.', 'danger')
        return redirect(url_for('recuperar_senha') if emails.disponivel() else url_for('login'))
    if request.method == 'POST':
        nova = request.form.get('nova_senha', '')
        if nova != request.form.get('confirmar_senha', ''):
            conn.close()
            flash('As duas senhas não coincidem.', 'danger')
            return render_template('redefinir_senha.html', token=token)
        forte, motivo = seguranca.senha_e_forte(nova)
        if not forte:
            conn.close()
            flash(motivo, 'danger')
            return render_template('redefinir_senha.html', token=token)
        alvo = conn.execute('SELECT * FROM utilizadores WHERE id = ? AND activo = 1', (registo['utilizador_id'],)).fetchone()
        if not alvo:
            conn.close()
            flash('Conta indisponível.', 'danger')
            return redirect(url_for('login'))
        conn.execute('UPDATE utilizadores SET password_hash = ?, deve_mudar_senha = 0 WHERE id = ?',
                     (generate_password_hash(nova), alvo['id']))
        seguranca.queimar_token_reset(conn, registo['id'])
        login_guard.limpar_conta(conn, alvo['username'])
        auditoria.registar(conn, 'repor_senha', f'{alvo["username"]} redefiniu a senha pela ligação enviada por e-mail',
                            utilizador=alvo['username'], ip=request.remote_addr)
        conn.commit()
        conn.close()
        session.clear()
        flash('Senha alterada. Entre com a nova senha' + (' e o código do 2FA.' if alvo['totp_ativo'] else '.'), 'success')
        return redirect(url_for('login'))
    conn.close()
    return render_template('redefinir_senha.html', token=token)


@app.route('/backup')
@super_admin_obrigatorio
def backup_pagina():
    return render_template('backup.html', backups=backup.listar_backups(),
                            pasta=backup.PASTA_BACKUPS, retencao=backup.RETENCAO_MAXIMA)


@app.route('/backup/executar', methods=['POST'])
@super_admin_obrigatorio
def backup_executar():
    caminho = backup.criar_backup()
    conn = get_connection()
    if caminho:
        auditoria.registar(conn, 'criar_backup', f'{session.get("utilizador")} gerou um backup manual',
                            utilizador=session.get('utilizador'), ip=request.remote_addr)
        flash(f'Backup criado: {os.path.basename(caminho)}', 'success')
    else:
        flash('Não foi possível criar o backup — base de dados ainda não existe.', 'warning')
    conn.commit()
    conn.close()
    return redirect(url_for('backup_pagina'))


@app.route('/backup/restaurar/<nome_ficheiro>', methods=['POST'])
@super_admin_obrigatorio
def backup_restaurar(nome_ficheiro):
    if request.form.get('confirmacao', '').strip().upper() != 'RESTAURAR':
        flash('Para restaurar escreva RESTAURAR na caixa de confirmação.', 'warning')
        return redirect(url_for('backup_pagina'))
    ok, msg = backup.restaurar_backup(nome_ficheiro)
    conn = get_connection()
    auditoria.registar(conn, 'restaurar_backup',
                        f'{session.get("utilizador")} restaurou o backup {nome_ficheiro}: {"sucesso" if ok else "FALHOU"}',
                        utilizador=session.get('utilizador'), ip=request.remote_addr, detalhes={'resultado': msg})
    conn.commit()
    conn.close()
    flash(msg, 'success' if ok else 'danger')
    return redirect(url_for('backup_pagina'))


@app.route('/backup/descarregar/<nome_ficheiro>')
@super_admin_obrigatorio
def backup_descarregar(nome_ficheiro):
    caminho = backup.caminho_seguro_do_backup(nome_ficheiro)
    if not caminho:
        abort(404)
    with open(caminho, 'rb') as f:
        conteudo = f.read()
    conn = get_connection()
    auditoria.registar(conn, 'descarregar_backup', f'{session.get("utilizador")} descarregou o backup {nome_ficheiro}',
                        utilizador=session.get('utilizador'), ip=request.remote_addr)
    conn.commit()
    conn.close()
    return Response(conteudo, mimetype='application/octet-stream',
                     headers={'Content-Disposition': f'attachment; filename="{nome_ficheiro}"'})


@app.route('/ong/verificar-duplicados', methods=['POST'])
@login_obrigatorio
@requer_permissao('criar')
def verificar_duplicados():
    """Endpoint AJAX chamado a partir do formulário (JS) enquanto a pessoa
    escreve, para avisar 'Possível duplicado — X% de correspondência'
    antes mesmo de submeter."""
    candidata = {
        'nome': request.form.get('nome', ''),
        'sigla': request.form.get('sigla', ''),
        'telefone': request.form.get('telefone', ''),
        'email': request.form.get('email', ''),
    }
    excluir_id = request.form.get('excluir_id', type=int)
    conn = get_connection()
    resultados = duplicados.procurar_possiveis_duplicados(conn, candidata, excluir_id=excluir_id)
    exacto = nome_ja_registado(conn, candidata['nome'], excluir_id=excluir_id)
    conn.close()
    return jsonify({'exacto': {'id': exacto['id'], 'nome': exacto['nome']} if exacto else None,
                    'parecidos': resultados})


@app.route('/duplicados')
@login_obrigatorio
@requer_permissao('aprovar')
def duplicados_pagina():
    conn = get_connection()
    pares = duplicados.varrer_todos_duplicados(conn)
    grupos = duplicados.agrupar_duplicados(pares)
    escopo_provincia = provincia_sessao()
    if escopo_provincia:
        grupos = [g for g in grupos if any(r['provincia'] == escopo_provincia for r in g['registos'])]
    conn.close()
    return render_template('duplicados.html', grupos=grupos, limiar=duplicados.LIMIAR_SUGESTAO)


@app.route('/duplicados/ignorar', methods=['POST'])
@login_obrigatorio
@requer_permissao('aprovar')
def duplicados_ignorar():
    ids = [int(x) for x in request.form.get('ids', '').split(',') if x.strip().isdigit()]
    if len(ids) < 2:
        flash('Pedido inválido.', 'danger')
        return redirect(url_for('duplicados_pagina'))
    conn = get_connection()
    duplicados.ignorar_grupo(conn, ids, session.get('utilizador'))
    auditoria.registar(conn, 'ignorar_duplicado',
                        f'{session.get("utilizador")} marcou as ONGs {", ".join("#" + str(i) for i in ids)} como não sendo duplicados',
                        utilizador=session.get('utilizador'), ip=request.remote_addr)
    conn.commit()
    conn.close()
    flash('Marcado como não sendo duplicado — não volta a ser sugerido.', 'info')
    return redirect(url_for('duplicados_pagina'))


@app.route('/sobreposicoes')
@login_obrigatorio
@requer_permissao('ver_auditoria')
def sobreposicoes_pagina():
    provincia = request.args.get('provincia', '').strip() or None
    limiar = request.args.get('limiar', sobreposicoes.LIMIAR_DEFEITO, type=int)
    escopo_provincia = provincia_sessao()
    if escopo_provincia:
        provincia = escopo_provincia

    conn = get_connection()
    grupos, total_geral = sobreposicoes.procurar_sobreposicoes(conn, provincia=provincia, limiar=limiar)
    conn.close()
    return render_template('sobreposicoes.html', grupos=grupos, total_geral=total_geral,
                            provincias=PROVINCIAS, provincia_filtro=provincia, limiar=limiar,
                            escopo_provincia=escopo_provincia)


@app.route('/sobreposicoes/ignorar', methods=['POST'])
@login_obrigatorio
@requer_permissao('ver_auditoria')
def sobreposicoes_ignorar():
    distrito_id = request.form.get('distrito_id', type=int)
    ramificacao_id = request.form.get('ramificacao_id', type=int)
    if not distrito_id or not ramificacao_id:
        flash('Pedido inválido.', 'danger')
        return redirect(url_for('sobreposicoes_pagina'))
    conn = get_connection()
    sobreposicoes.ignorar_sobreposicao(conn, distrito_id, ramificacao_id, session.get('utilizador'))
    auditoria.registar(conn, 'ignorar_sobreposicao',
                        f'{session.get("utilizador")} marcou uma sobreposição de actuação como já coordenada',
                        utilizador=session.get('utilizador'), ip=request.remote_addr,
                        detalhes={'distrito_id': distrito_id, 'ramificacao_id': ramificacao_id})
    conn.commit()
    conn.close()
    flash('Marcado como já coordenado — não volta a ser sinalizado.', 'info')
    return redirect(url_for('sobreposicoes_pagina'))


@app.route('/importar', methods=['GET'])
@login_obrigatorio
@requer_permissao('criar')
def importar_pagina():
    return render_template('importar.html')


@app.route('/importar/pre-visualizar', methods=['POST'])
@login_obrigatorio
@requer_permissao('criar')
def importar_pre_visualizar():
    ficheiro = request.files.get('ficheiro')
    if not ficheiro or not ficheiro.filename:
        flash('Escolha um ficheiro Excel (.xlsx) para importar.', 'danger')
        return redirect(url_for('importar_pagina'))
    if not ficheiro.filename.lower().endswith(('.xlsx', '.xlsm')):
        flash('Só são aceites ficheiros .xlsx — se tiver um .xls antigo, converta primeiro '
              '(ver converter_xls_para_xlsx.py).', 'danger')
        return redirect(url_for('importar_pagina'))

    pasta_temp = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tmp_uploads')
    os.makedirs(pasta_temp, exist_ok=True)
    nome_seguro = secure_filename(ficheiro.filename)
    caminho_temp = os.path.join(pasta_temp, f'{uuid.uuid4().hex}_{nome_seguro}')
    ficheiro.save(caminho_temp)

    try:
        hash_f = importacao_web.hash_ficheiro(caminho_temp)
        conn_h = get_connection()
        ja = conn_h.execute('SELECT nome_ficheiro, criado_em FROM importacoes_feitas WHERE hash_ficheiro = ?', (hash_f,)).fetchone()
        conn_h.close()
        if ja:
            os.remove(caminho_temp)
            flash(f'Este ficheiro já foi importado em {ja["criado_em"]} ("{ja["nome_ficheiro"]}"). '
                  'Importar o mesmo ficheiro duas vezes duplicaria registos — se há dados novos, envie a versão actualizada.', 'warning')
            return redirect(url_for('importar_pagina'))
        registos, nome_ficheiro = importacao_web.processar_upload(caminho_temp)
    except Exception as e:
        print(f'[importar_pre_visualizar] erro ao ler "{nome_seguro}": {e}')
        flash('Não consegui ler este ficheiro. Confirme que é uma matriz no layout padrão '
              '(coluna "Designação da Organização") e que não está corrompido.', 'danger')
        return redirect(url_for('importar_pagina'))
    finally:
        if os.path.exists(caminho_temp):
            os.remove(caminho_temp)

    if not registos:
        flash('Não encontrei nenhum registo neste ficheiro — confirme o layout, ou use o '
              'pipeline por linha de comandos para layouts especiais.', 'warning')
        return redirect(url_for('importar_pagina'))

    conn = get_connection()
    escopo_provincia = provincia_sessao()
    registos_validados = importacao_web.validar_registos(conn, registos, escopo_provincia=escopo_provincia)
    conn.close()

    token = importacao_web.guardar_pre_visualizacao(nome_ficheiro, registos_validados, session.get('utilizador'), hash_f)
    return redirect(url_for('importar_pre_visualizacao', token=token))


@app.route('/importar/pre-visualizacao/<token>')
@login_obrigatorio
@requer_permissao('criar')
def importar_pre_visualizacao(token):
    entrada = importacao_web.obter_pre_visualizacao(token, utilizador=session.get('utilizador'))
    if not entrada:
        flash('Esta pré-visualização expirou ou não existe. Envie o ficheiro novamente.', 'warning')
        return redirect(url_for('importar_pagina'))
    resumo = importacao_web.resumo_contagens(entrada['registos'])
    return render_template('importar_preview.html', token=token, nome_ficheiro=entrada['nome_ficheiro'],
                            registos=entrada['registos'], resumo=resumo)


@app.route('/importar/confirmar/<token>', methods=['POST'])
@login_obrigatorio
@requer_permissao('criar')
def importar_confirmar(token):
    entrada = importacao_web.obter_pre_visualizacao(token, utilizador=session.get('utilizador'))
    if not entrada:
        flash('Esta pré-visualização expirou ou não existe. Envie o ficheiro novamente.', 'warning')
        return redirect(url_for('importar_pagina'))

    indices_escolhidos = {int(i) for i in request.form.getlist('incluir')}
    aprovacao = 'Aprovado' if e_super_admin() else 'Pendente'
    fase_workflow = 'Publicada' if aprovacao == 'Aprovado' else 'Submetida'

    conn = get_connection()
    total_importados = 0
    # Revalida AGORA contra a base de dados (podem ter sido criadas ONGs desde a
    # pré-visualização) e no servidor — nunca confia nos estados enviados pelo browser.
    revalidados = importacao_web.validar_registos(conn, entrada['registos'], escopo_provincia=provincia_sessao())
    for indice, registo in enumerate(revalidados):
        if indice not in indices_escolhidos or registo['status'] in ('erro', 'duplicado_exato'):
            continue
        importador_cli.importar_linha(conn, registo, aprovacao=aprovacao,
                                       criado_por=session.get('utilizador'), fase_workflow=fase_workflow)
        total_importados += 1

    if total_importados and entrada.get('hash'):
        conn.execute('INSERT OR IGNORE INTO importacoes_feitas (hash_ficheiro, nome_ficheiro, utilizador, total) VALUES (?, ?, ?, ?)',
                     (entrada['hash'], entrada['nome_ficheiro'], session.get('utilizador'), total_importados))
    if total_importados:
        auditoria.registar(conn, 'importar_matriz',
                            f'{session.get("utilizador")} importou {total_importados} ONG(s) do ficheiro '
                            f'"{entrada["nome_ficheiro"]}" ({aprovacao})',
                            utilizador=session.get('utilizador'), ip=request.remote_addr,
                            detalhes={'ficheiro': entrada['nome_ficheiro'], 'total': total_importados})
    conn.commit()
    conn.close()

    importacao_web.remover_pre_visualizacao(token)

    if total_importados:
        estado_txt = 'aprovadas automaticamente' if aprovacao == 'Aprovado' else 'enviadas para aprovação'
        flash(f'{total_importados} ONG(s) importada(s) com sucesso ({estado_txt}).', 'success')
    else:
        flash('Nenhum registo foi seleccionado para importar.', 'info')
    return redirect(url_for('index'))


@app.route('/importar/cancelar/<token>', methods=['POST'])
@login_obrigatorio
@requer_permissao('criar')
def importar_cancelar(token):
    importacao_web.remover_pre_visualizacao(token)
    flash('Importação cancelada — nada foi gravado.', 'info')
    return redirect(url_for('importar_pagina'))


# ─── AGENDAMENTO DE BACKUPS ────────────────────────────────────────────────────
# Corre uma vez quando o processo arranca (também sob wsgi.py/waitress em
# produção, já que este código está ao nível do módulo). O bloqueio evita
# duplicar o agendador quando o recarregador do Flask em modo debug arranca
# dois processos.
if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
    backup.iniciar_agendamento_diario()


if __name__ == '__main__':
    init_db()
    app.run(debug=True)
