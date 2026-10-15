"""2FA obrigatório, códigos de recuperação, anti-replay, recuperação de senha por e-mail,
produção sem contas de demonstração e matriz de permissões sobre todas as rotas."""
import os
import re
import subprocess
import sys
import time

import pyotp
import pytest

import app as app_modulo
import database
import emails
import seguranca
from conftest import Cliente, SENHA, cliente_com, criar_conta, texto, RAIZ

PERFIS = ['super_admin', 'admin', 'gestor_nacional', 'gestor_provincial', 'operador', 'consulta']


@pytest.fixture
def exigir_2fa(monkeypatch):
    monkeypatch.setattr(app_modulo, 'EXIGIR_2FA_ADMIN', True)


def _seg(email):
    conn = database.get_connection()
    r = conn.execute('SELECT totp_secret FROM utilizadores WHERE username=?', (email,)).fetchone()[0]
    conn.close()
    return r


def _activar(c, deslocamento=0):
    c.get('/conta/2fa/configurar')
    seg = _seg(c.email)
    return seg, c.post('/conta/2fa/activar', {'codigo': pyotp.TOTP(seg).at(time.time() + deslocamento)})


# ── 2FA obrigatório para administradores ───────────────────────────────────
@pytest.mark.parametrize('perfil', ['super_admin', 'admin'])
def test_administrador_sem_2fa_so_acede_a_configuracao(perfil, exigir_2fa):
    c = cliente_com(perfil)
    for rota in ('/utilizadores', '/ongs', '/pendentes', '/backup', '/relatorios', '/ong/novo', '/admin/noticias'):
        r = c.get(rota)
        assert r.status_code == 302 and '/conta/2fa/configurar' in r.headers['Location'], (rota, r.status_code)
    assert c.post('/utilizadores/novo', {'email': 'x@x.mz', 'nome_completo': 'X', 'senha': 'Abcdefgh1234', 'perfil': 'consulta'}).status_code == 302
    conn = database.get_connection()
    assert conn.execute("SELECT COUNT(*) FROM utilizadores WHERE email='x@x.mz'").fetchone()[0] == 0
    assert c.get('/conta/2fa/configurar').status_code == 200
    assert c.get('/conta').status_code == 200
    assert c.get('/logout').status_code == 302


def test_depois_de_activar_o_2fa_fica_livre_e_recebe_codigos(exigir_2fa):
    c = cliente_com('admin')
    seg, r = _activar(c)
    assert r.status_code == 200 and 'Códigos de recuperação' in texto(r)
    assert len(re.findall(r'\b[A-Z2-9]{5}-[A-Z2-9]{5}\b', texto(r))) == 10
    assert 'no-store' in r.headers.get('Cache-Control', '')
    assert c.get('/utilizadores').status_code == 200


@pytest.mark.parametrize('perfil', ['gestor_nacional', 'gestor_provincial', 'operador', 'consulta'])
def test_outros_perfis_nao_sao_obrigados(perfil, exigir_2fa):
    c = cliente_com(perfil, 'Sofala' if perfil == 'gestor_provincial' else None)
    assert c.get('/conta').status_code == 200
    assert c.get('/ongs').status_code == 200


def test_administrador_nao_pode_desactivar_o_proprio_2fa(exigir_2fa):
    c = cliente_com('admin')
    _activar(c)
    c.post('/conta/2fa/desactivar', {'senha_actual': SENHA})
    conn = database.get_connection()
    assert conn.execute('SELECT totp_ativo FROM utilizadores WHERE username=?', (c.email,)).fetchone()[0] == 1


def test_reposicao_do_2fa_por_outro_admin_obriga_a_reconfigurar(exigir_2fa):
    alvo = cliente_com('admin')
    _activar(alvo)
    conn = database.get_connection()
    uid = conn.execute('SELECT id FROM utilizadores WHERE username=?', (alvo.email,)).fetchone()[0]
    chefe = cliente_com('super_admin', ip='10.0.0.2')
    _activar(chefe)
    assert chefe.post(f'/utilizadores/{uid}/repor-2fa').status_code == 302
    novo = Cliente('10.0.0.3')
    assert novo.login(alvo.email).status_code == 302
    assert '/conta/2fa/configurar' in novo.get('/utilizadores').headers['Location']
    assert conn.execute('SELECT COUNT(*) FROM codigos_recuperacao_2fa WHERE utilizador_id=?', (uid,)).fetchone()[0] == 0


# ── anti-replay e códigos de recuperação ───────────────────────────────────
def test_codigo_totp_nao_pode_ser_reutilizado():
    c = cliente_com('operador')
    seg, _ = _activar(c)
    proximo = pyotp.TOTP(seg).at(time.time() + 30)
    a = Cliente('10.5.1.1'); a.login(c.email)
    assert a.post('/login/2fa', {'codigo': proximo}).status_code == 302
    b = Cliente('10.5.1.2'); b.login(c.email)
    r = b.post('/login/2fa', {'codigo': proximo})            # o mesmo código, outra sessão
    assert r.status_code == 200 and 'inválido' in texto(r)


def _codigos(c):
    r = c.post('/conta/2fa/codigos', {'senha_actual': SENHA})
    return re.findall(r'\b[A-Z2-9]{5}-[A-Z2-9]{5}\b', texto(r))


def test_codigo_de_recuperacao_entra_uma_so_vez():
    c = cliente_com('operador')
    _activar(c)
    codigos = _codigos(c)
    assert len(codigos) == 10
    a = Cliente('10.5.2.1'); a.login(c.email)
    assert a.post('/login/2fa', {'codigo': codigos[0].lower()}).status_code == 302   # aceita minúsculas
    assert a.get('/conta').status_code == 200
    b = Cliente('10.5.2.2'); b.login(c.email)
    assert b.post('/login/2fa', {'codigo': codigos[0]}).status_code == 200          # já queimado
    assert b.post('/login/2fa', {'codigo': codigos[1]}).status_code == 302          # outro serve
    conn = database.get_connection()
    assert conn.execute("SELECT COUNT(*) FROM historico_auditoria WHERE accao='login_2fa_recuperacao'").fetchone()[0] == 2


def test_gerar_novos_codigos_invalida_os_antigos_e_exige_senha():
    c = cliente_com('operador')
    _activar(c)
    velhos = _codigos(c)
    assert c.post('/conta/2fa/codigos', {'senha_actual': 'errada'}).status_code == 302
    novos = _codigos(c)
    assert set(velhos).isdisjoint(novos)
    a = Cliente('10.5.3.1'); a.login(c.email)
    assert a.post('/login/2fa', {'codigo': velhos[0]}).status_code == 200


def test_codigos_de_recuperacao_so_ficam_em_hash():
    c = cliente_com('operador')
    _activar(c)
    codigos = _codigos(c)
    conn = database.get_connection()
    guardado = ' '.join(r[0] for r in conn.execute('SELECT codigo_hash FROM codigos_recuperacao_2fa'))
    assert all(x.replace('-', '') not in guardado for x in codigos)


def test_adivinhar_codigos_de_recuperacao_e_bloqueado():
    c = cliente_com('operador')
    _activar(c)
    a = Cliente('10.5.4.1'); a.login(c.email)
    for i in range(5):
        a.post('/login/2fa', {'codigo': f'ABCDE-FGH{i}J'})
    codigos = _codigos(c)
    r = a.post('/login/2fa', {'codigo': codigos[0]})
    assert r.status_code == 302 and '2fa' not in r.headers['Location']


# ── recuperação de senha por e-mail ────────────────────────────────────────
@pytest.fixture
def smtp(monkeypatch):
    monkeypatch.setenv('SGIONGS_SMTP_HOST', 'smtp.exemplo.invalid')
    monkeypatch.setenv('SGIONGS_SMTP_FROM', 'sgiong@exemplo.invalid')
    monkeypatch.setenv('SGIONGS_URL_BASE', 'https://sgiong.exemplo.invalid')
    enviados = []
    monkeypatch.setattr(emails, 'enviar', lambda para, assunto, corpo: enviados.append((para, corpo)) or True)
    return enviados


def _token(enviados):
    return re.search(r'/recuperar-senha/([\w\-]+)', enviados[-1][1]).group(1)


def test_sem_smtp_recuperacao_fica_desligada(anonimo, monkeypatch):
    monkeypatch.delenv('SGIONGS_SMTP_HOST', raising=False)
    assert anonimo.get('/recuperar-senha').status_code == 302
    assert '/recuperar-senha' not in texto(anonimo.get('/login'))


def test_recuperacao_fluxo_completo(anonimo, smtp):
    email = criar_conta('operador', email='maria@x.mz')
    assert '/recuperar-senha' in texto(anonimo.get('/login'))
    r = anonimo.post('/recuperar-senha', {'email': 'MARIA@x.mz'})
    assert r.status_code == 302
    assert len(smtp) == 1 and smtp[0][0] == 'maria@x.mz'
    assert 'https://sgiong.exemplo.invalid/recuperar-senha/' in smtp[0][1]     # URL base fixa, não do cabeçalho Host
    token = _token(smtp)
    assert anonimo.get(f'/recuperar-senha/{token}').status_code == 200
    r = anonimo.post(f'/recuperar-senha/{token}', {'nova_senha': 'Nova-Senha-2026x', 'confirmar_senha': 'Nova-Senha-2026x'})
    assert r.status_code == 302
    assert Cliente('10.8.0.1').login(email, 'Nova-Senha-2026x').status_code == 302
    assert Cliente('10.8.0.2').login(email, SENHA).status_code == 200                 # a antiga já não serve
    # uso único
    assert anonimo.get(f'/recuperar-senha/{token}').status_code == 302


def test_recuperacao_nao_revela_se_o_email_existe(anonimo, smtp):
    criar_conta('operador', email='existe@x.mz')
    a = anonimo.post('/recuperar-senha', {'email': 'existe@x.mz'}, follow_redirects=True)
    b = anonimo.post('/recuperar-senha', {'email': 'naoexiste@x.mz'}, follow_redirects=True)
    msg = lambda r: re.search(r'Se o e-mail corresponder[^<]*', texto(r)).group(0)
    assert msg(a) == msg(b)
    assert len(smtp) == 1


def test_token_expira_e_pedido_novo_invalida_o_anterior(anonimo, smtp, monkeypatch):
    criar_conta('operador', email='ana@x.mz')
    anonimo.post('/recuperar-senha', {'email': 'ana@x.mz'})
    antigo = _token(smtp)
    anonimo.post('/recuperar-senha', {'email': 'ana@x.mz'})
    novo = _token(smtp)
    assert antigo != novo
    assert anonimo.get(f'/recuperar-senha/{antigo}').status_code == 302            # substituído
    real = time.time
    monkeypatch.setattr(time, 'time', lambda: real() + 31 * 60)
    assert anonimo.get(f'/recuperar-senha/{novo}').status_code == 302              # expirado


def test_token_so_fica_em_hash_e_lixo_e_recusado(anonimo, smtp):
    criar_conta('operador', email='ana@x.mz')
    anonimo.post('/recuperar-senha', {'email': 'ana@x.mz'})
    token = _token(smtp)
    conn = database.get_connection()
    assert token not in ' '.join(r[0] for r in conn.execute('SELECT token_hash FROM reset_senha_tokens'))
    for lixo in ('abc', 'x' * 500, "' OR 1=1 --"):
        assert anonimo.get(f'/recuperar-senha/{lixo}').status_code in (302, 404)


def test_recuperacao_aplica_politica_de_senha(anonimo, smtp):
    criar_conta('operador', email='ana@x.mz')
    anonimo.post('/recuperar-senha', {'email': 'ana@x.mz'})
    token = _token(smtp)
    r = anonimo.post(f'/recuperar-senha/{token}', {'nova_senha': 'curta1', 'confirmar_senha': 'curta1'})
    assert r.status_code == 200
    r = anonimo.post(f'/recuperar-senha/{token}', {'nova_senha': 'Longa-Senha-2026', 'confirmar_senha': 'outra'})
    assert r.status_code == 200
    assert anonimo.get(f'/recuperar-senha/{token}').status_code == 200              # continua válido após erros


def test_recuperacao_limita_pedidos_e_nao_ataca_contas_inactivas(anonimo, smtp):
    criar_conta('operador', email='ana@x.mz')
    for _ in range(8):
        anonimo.post('/recuperar-senha', {'email': 'ana@x.mz'})
    assert len(smtp) == 5                                                           # limite por e-mail
    conn = database.get_connection()
    conn.execute("UPDATE utilizadores SET activo=0 WHERE email='ana@x.mz'")
    conn.commit()
    n = len(smtp)
    anonimo.post('/recuperar-senha', {'email': 'ana@x.mz'}); assert len(smtp) == n


def test_recuperacao_de_senha_nao_contorna_o_2fa(anonimo, smtp):
    c = cliente_com('operador')
    _activar(c)
    anonimo.post('/recuperar-senha', {'email': c.email})
    token = _token(smtp)
    anonimo.post(f'/recuperar-senha/{token}', {'nova_senha': 'Nova-Senha-2026x', 'confirmar_senha': 'Nova-Senha-2026x'})
    novo = Cliente('10.8.1.1')
    r = novo.login(c.email, 'Nova-Senha-2026x')
    assert r.status_code == 302 and '/login/2fa' in r.headers['Location']
    assert novo.get('/ongs').status_code in (200, 302)
    assert novo.get('/utilizadores').status_code == 302                              # sem o código, nada


def test_pedido_e_redefinicao_ficam_na_auditoria(anonimo, smtp):
    criar_conta('operador', email='ana@x.mz')
    anonimo.post('/recuperar-senha', {'email': 'ana@x.mz'})
    anonimo.post(f'/recuperar-senha/{_token(smtp)}', {'nova_senha': 'Nova-Senha-2026x', 'confirmar_senha': 'Nova-Senha-2026x'})
    conn = database.get_connection()
    accoes = [r[0] for r in conn.execute('SELECT accao FROM historico_auditoria')]
    assert 'pedido_recuperacao_senha' in accoes and 'repor_senha' in accoes


# ── produção: nada de demonstração ─────────────────────────────────────────
def _py(codigo, **env):
    e = dict(os.environ); e.update(env)
    return subprocess.run([sys.executable, '-c', codigo], cwd=RAIZ, env=e, capture_output=True, text=True)


def test_producao_recusa_contas_legadas_mesmo_com_hash_proprio():
    from werkzeug.security import generate_password_hash
    h = generate_password_hash('Senha-Propria-2026')
    codigo = '''
import app
c = app.app.test_client()
c.get("/login", base_url="https://localhost")
with c.session_transaction() as s: t = s["csrf_token"]
for u, p in [("superadmin", "Senha-Propria-2026"), ("adminong", "Senha-Propria-2026"), ("superadmin", "superadmin2026")]:
    r = c.post("/login", data={"utilizador": u, "senha": p, "csrf_token": t}, base_url="https://localhost")
    print(r.status_code)
'''
    r = _py(codigo, SGIONGS_PRODUCAO='1', SGIONGS_SECRET_KEY='x', SGIONGS_SUPERADMIN_PASSWORD_HASH=h,
            SGIONGS_ADMIN_PASSWORD_HASH=h, SGIONGS_DB_PATH=os.path.join(os.environ['SGIONGS_DATA_DIR'], 'p2.db'))
    assert r.returncode == 0, r.stderr
    assert set(r.stdout.split()) <= {'200', '429'}, r.stdout


def test_producao_exige_2fa_por_omissao_e_pode_ser_lido_da_configuracao():
    r = _py('import config; print(config.EXIGIR_2FA_ADMIN, config.LEGADO_ADMIN_ACTIVO, config.LEGADO_SUPERADMIN_ACTIVO)',
            SGIONGS_PRODUCAO='1')
    assert r.stdout.split() == ['True', 'False', 'False']


def test_super_admin_inicial_em_producao_e_obrigado_a_2fa_e_senha():
    codigo = '''
import app
c = app.app.test_client()
c.get("/login", base_url="https://localhost")
with c.session_transaction() as s: t = s["csrf_token"]
c.post("/login", data={"utilizador": "primeiro@mpd.gov.mz", "senha": "Arranque-2026-xyz", "csrf_token": t}, base_url="https://localhost")
print(c.get("/utilizadores", base_url="https://localhost").headers.get("Location"))
c.get("/conta", base_url="https://localhost")
with c.session_transaction() as s: t = s["csrf_token"]
c.post("/conta/senha", data={"senha_actual": "Arranque-2026-xyz", "nova_senha": "Definitiva-2026-abc", "confirmar_senha": "Definitiva-2026-abc", "csrf_token": t}, base_url="https://localhost")
print(c.get("/utilizadores", base_url="https://localhost").headers.get("Location"))
'''
    r = _py(codigo, SGIONGS_PRODUCAO='1', SGIONGS_SECRET_KEY='x',
            SGIONGS_BOOTSTRAP_EMAIL='primeiro@mpd.gov.mz', SGIONGS_BOOTSTRAP_PASSWORD='Arranque-2026-xyz',
            SGIONGS_DB_PATH=os.path.join(os.environ['SGIONGS_DATA_DIR'], 'boot2.db'))
    assert r.returncode == 0, r.stderr
    l = r.stdout.split('\n')
    assert '/conta' in l[0] and '/conta/2fa/configurar' in l[1]


# ── matriz de permissões sobre TODAS as rotas ──────────────────────────────
# endpoint -> perfis autorizados (None = qualquer utilizador autenticado). Rotas públicas à parte.
PUBLICAS = {'login', 'login_2fa', 'logout', 'saude', 'inicio', 'noticias_lista', 'noticia_detalhe', 'chatbot_perguntar',
            'index', 'organizacoes', 'dashboard', 'levantamento_nacional', 'sector', 'detalhe', 'static',
            'recuperar_senha', 'redefinir_senha'}
ADMINS = {'super_admin', 'admin'}
GESTORES = {'super_admin', 'admin', 'gestor_nacional', 'gestor_provincial'}
ESCRITORES = GESTORES | {'operador'}
AUTORIZACAO = {
    'noticias_admin': ADMINS, 'capa_inicio_guardar': ADMINS, 'noticia_nova': ADMINS, 'noticia_editar': ADMINS,
    'noticia_publicar': ADMINS, 'noticia_eliminar': ADMINS,
    'utilizadores': ADMINS, 'novo_utilizador': ADMINS, 'criar_gestores_provinciais': ADMINS,
    'repor_senha_utilizador': ADMINS, 'repor_2fa_utilizador': ADMINS, 'alterar_email_utilizador': ADMINS,
    'desactivar_utilizador': ADMINS,
    'backup_pagina': {'super_admin'}, 'backup_executar': {'super_admin'}, 'backup_restaurar': {'super_admin'},
    'backup_descarregar': {'super_admin'}, 'eliminar': {'super_admin'},
    'auditoria_geral': GESTORES, 'pendentes': GESTORES,
    'aprovar': GESTORES, 'rejeitar': GESTORES, 'aprovar_edicao': GESTORES, 'rejeitar_edicao': GESTORES,
    'iniciar_analise': GESTORES, 'sinalizar_atualizacao': GESTORES,
    'duplicados_pagina': GESTORES, 'duplicados_ignorar': GESTORES, 'sobreposicoes_pagina': GESTORES,
    'sobreposicoes_ignorar': GESTORES,
    'novo': ESCRITORES, 'editar': ESCRITORES, 'verificar_duplicados': ESCRITORES, 'rascunhos': ESCRITORES,
    'eliminar_rascunho': ESCRITORES,
    'importar_pagina': ESCRITORES, 'importar_pre_visualizar': ESCRITORES, 'importar_pre_visualizacao': ESCRITORES,
    'importar_confirmar': ESCRITORES, 'importar_cancelar': ESCRITORES,
}
# autenticados, qualquer perfil
QUALQUER_LOGIN = {'relatorios_pagina', 'relatorio_pdf', 'relatorio_excel', 'relatorio_csv', 'conta', 'alterar_propria_senha',
                  'configurar_2fa', 'qrcode_2fa', 'activar_2fa', 'desactivar_2fa', 'regenerar_codigos_2fa'}


def _url(rule, ong=1):
    u = re.sub(r'<int:\w+>', str(ong), rule.rule)
    return re.sub(r'<(?:path:)?\w+>', 'x', u)


def test_toda_a_rota_esta_classificada():
    """Falha se alguém criar uma rota nova sem a declarar pública, de perfil ou de qualquer-login."""
    conhecidas = PUBLICAS | set(AUTORIZACAO) | QUALQUER_LOGIN
    desconhecidas = {r.endpoint for r in app_modulo.app.url_map.iter_rules()
                     if r.endpoint not in conhecidas and not r.endpoint.startswith('api')}
    assert not desconhecidas, f'Rotas sem classificação de permissões: {sorted(desconhecidas)}'


@pytest.mark.parametrize('perfil', PERFIS)
def test_perfil_so_entra_onde_pode(perfil, db):
    """Para cada rota restrita e cada perfil: não autorizado nunca vê 200/modifica; é redireccionado ou recebe 403."""
    c = cliente_com(perfil, 'Sofala' if perfil == 'gestor_provincial' else None)
    ong = db.execute("SELECT id FROM ongs WHERE aprovacao='Aprovado' AND provincia='Sofala' LIMIT 1").fetchone()[0]
    total_ongs = db.execute('SELECT COUNT(*) FROM ongs').fetchone()[0]
    total_utl = db.execute('SELECT COUNT(*) FROM utilizadores').fetchone()[0]
    indevidos = []
    for rule in app_modulo.app.url_map.iter_rules():
        ep = rule.endpoint
        if ep not in AUTORIZACAO or perfil in AUTORIZACAO[ep]:
            continue
        for metodo in rule.methods & {'GET', 'POST'}:
            url = _url(rule, ong)
            r = c.get(url) if metodo == 'GET' else c.post(url, {'confirmacao': 'RESTAURAR'})
            if r.status_code not in (302, 403, 404):
                indevidos.append((ep, metodo, r.status_code))
    assert not indevidos, f'{perfil} conseguiu: {indevidos}'
    assert db.execute('SELECT COUNT(*) FROM ongs').fetchone()[0] == total_ongs
    assert db.execute('SELECT COUNT(*) FROM utilizadores').fetchone()[0] == total_utl


def test_conta_desactivada_perde_a_sessao_activa(super_admin, db):
    alvo = cliente_com('operador', ip='10.3.3.3')
    uid = db.execute('SELECT id FROM utilizadores WHERE username=?', (alvo.email,)).fetchone()[0]
    assert alvo.get('/ong/novo').status_code == 200
    super_admin.post(f'/utilizadores/{uid}/desactivar')
    assert alvo.get('/ong/novo').status_code == 302


def test_despromocao_aplica_se_na_hora(super_admin, db):
    alvo = cliente_com('gestor_nacional', ip='10.3.4.4')
    uid = db.execute('SELECT id FROM utilizadores WHERE username=?', (alvo.email,)).fetchone()[0]
    assert alvo.get('/pendentes').status_code == 200
    db.execute("UPDATE utilizadores SET perfil='consulta' WHERE id=?", (uid,))
    db.commit()
    assert alvo.get('/pendentes').status_code == 302
