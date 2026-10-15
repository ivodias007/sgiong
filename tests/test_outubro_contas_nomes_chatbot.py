"""Contas provinciais, login por e-mail, nomes repetidos, chatbot, distritos,
classificação completa das rotas e uploads."""
import io
import re
import pytest
from conftest import Cliente, cliente_com, criar_conta, SENHA, texto
import database
import tagging
import contas_iniciais

PERFIS = ['super_admin', 'admin', 'gestor_nacional', 'gestor_provincial', 'operador', 'consulta']


# ── 11 contas provinciais ──────────────────────────────────────────────────
def _gestores(db):
    return db.execute("SELECT * FROM utilizadores WHERE perfil='gestor_provincial'").fetchall()


def test_cria_11_contas_sem_duplicar(super_admin, db):
    assert len(tagging.PROVINCIAS) == 11
    r = super_admin.post('/utilizadores/gestores-provinciais', {'dominio': 'mpd.gov.mz'})
    assert r.status_code == 200
    g = _gestores(db)
    assert len(g) == 11
    assert {x['provincia'] for x in g} == set(tagging.PROVINCIAS)
    assert len({x['email'].lower() for x in g}) == 11
    assert all(x['deve_mudar_senha'] == 1 for x in g)
    # repetir não cria nada
    super_admin.post('/utilizadores/gestores-provinciais', {'dominio': 'mpd.gov.mz'})
    assert len(_gestores(db)) == 11
    # outro domínio também não duplica a província
    super_admin.post('/utilizadores/gestores-provinciais', {'dominio': 'outro.gov.mz'})
    assert len(_gestores(db)) == 11


def test_segunda_conta_para_a_mesma_provincia_e_recusada(super_admin, db):
    super_admin.post('/utilizadores/novo', {'email': 'a@x.mz', 'nome_completo': 'A', 'senha': 'Abcdefgh1234',
                                             'perfil': 'gestor_provincial', 'provincia': 'Sofala'})
    super_admin.post('/utilizadores/novo', {'email': 'b@x.mz', 'nome_completo': 'B', 'senha': 'Abcdefgh1234',
                                             'perfil': 'gestor_provincial', 'provincia': 'Sofala'})
    assert len(db.execute("SELECT 1 FROM utilizadores WHERE perfil='gestor_provincial' AND provincia='Sofala'").fetchall()) == 1


def test_indice_unico_impede_duplicar_mesmo_por_sql(db):
    criar_conta('gestor_provincial', 'Tete', email='um@x.mz')
    with pytest.raises(Exception):
        criar_conta('gestor_provincial', 'Tete', email='dois@x.mz')


def test_email_duplicado_recusado(super_admin, db):
    criar_conta('operador', email='dup@x.mz')
    super_admin.post('/utilizadores/novo', {'email': 'DUP@x.mz', 'nome_completo': 'D', 'senha': 'Abcdefgh1234', 'perfil': 'operador'})
    assert db.execute("SELECT COUNT(*) FROM utilizadores WHERE lower(email)='dup@x.mz'").fetchone()[0] == 1


@pytest.mark.parametrize('perfil', ['gestor_nacional', 'gestor_provincial', 'operador', 'consulta'])
def test_so_administradores_criam_contas_provinciais(perfil, db):
    c = cliente_com(perfil, 'Sofala' if perfil == 'gestor_provincial' else None)
    antes = len(_gestores(db))
    c.post('/utilizadores/gestores-provinciais', {'dominio': 'mpd.gov.mz'})
    assert len(_gestores(db)) == antes


def test_conta_nova_e_obrigada_a_mudar_senha(super_admin, db):
    super_admin.post('/utilizadores/gestores-provinciais', {'dominio': 'mpd.gov.mz'})
    # define senha conhecida para a conta de Sofala sem tocar no flag
    from werkzeug.security import generate_password_hash
    db.execute("UPDATE utilizadores SET password_hash=? WHERE perfil='gestor_provincial' AND provincia='Sofala'",
               (generate_password_hash(SENHA),))
    db.commit()
    email = db.execute("SELECT email FROM utilizadores WHERE provincia='Sofala' AND perfil='gestor_provincial'").fetchone()[0]
    c = Cliente('10.9.9.9')
    assert c.login(email.upper()).status_code == 302          # entra com e-mail em maiúsculas
    r = c.get('/ongs')
    assert r.status_code == 302 and '/conta' in r.headers['Location']
    assert c.get('/conta').status_code == 200
    c.post('/conta/senha', {'senha_actual': SENHA, 'nova_senha': 'Nova-Senha-2026x', 'confirmar_senha': 'Nova-Senha-2026x'})
    assert c.get('/ongs').status_code == 200


# ── nomes repetidos ────────────────────────────────────────────────────────
def test_nome_repetido_bloqueado_para_todos_os_perfis_que_criam(db):
    nome = db.execute("SELECT nome FROM ongs WHERE aprovacao='Aprovado' LIMIT 1").fetchone()[0]
    antes = db.execute('SELECT COUNT(*) FROM ongs').fetchone()[0]
    for perfil in ('super_admin', 'admin', 'operador'):
        c = cliente_com(perfil)
        for variante in (nome, nome.upper(), '  ' + nome.lower() + ' '):
            c.post('/ong/novo', {'nome': variante, 'provincias': ['Sofala'], 'natureza': 'ONG', 'origem': 'Nacional',
                                 'area_intervencao': 'Saúde', 'estado': 'Ativo'})
    assert db.execute('SELECT COUNT(*) FROM ongs').fetchone()[0] == antes


def test_verificar_duplicados_devolve_exacto(super_admin, db):
    nome = db.execute("SELECT nome FROM ongs WHERE aprovacao='Aprovado' LIMIT 1").fetchone()[0]
    r = super_admin.post('/ong/verificar-duplicados', {'nome': nome.upper()})
    assert r.get_json()['exacto']['nome'] == nome
    r = super_admin.post('/ong/verificar-duplicados', {'nome': 'Organização Totalmente Inexistente Zyx'})
    assert r.get_json()['exacto'] is None


# ── chatbot ────────────────────────────────────────────────────────────────
def test_chatbot_publico_e_numeros_certos(anonimo, db):
    r = anonimo.get('/chatbot/perguntar?q=quantas ongs em sofala')
    assert r.status_code == 200
    esperado = db.execute("""SELECT COUNT(DISTINCT op.ong_id) FROM ong_provincias op JOIN ongs o ON o.id=op.ong_id
                             WHERE o.aprovacao='Aprovado' AND o.rascunho=0 AND op.provincia='Sofala'""").fetchone()[0]
    assert str(esperado) in r.get_json()['resposta']
    for q in ('', 'x' * 5000, "'; DROP TABLE ongs;--", '<script>alert(1)</script>'):
        assert anonimo.get('/chatbot/perguntar', query_string={'q': q}).status_code == 200
    assert db.execute('SELECT COUNT(*) FROM ongs').fetchone()[0] > 800


def test_chatbot_nao_conta_pendentes(anonimo, db):
    db.execute("UPDATE ongs SET aprovacao='Pendente' WHERE id IN (SELECT ong_id FROM ong_provincias WHERE provincia='Sofala')")
    db.commit()
    resp = anonimo.get('/chatbot/perguntar?q=quantas ongs em sofala').get_json()['resposta']
    assert '298' not in resp and not re.search(r'\\b[1-9]\\d* ONGs', resp)


# ── filtros de distrito ────────────────────────────────────────────────────
def test_filtro_distrito_bate_com_a_base(anonimo, db):
    d = db.execute("SELECT d.id, d.nome, d.provincia FROM distritos d WHERE d.provincia='Sofala' AND d.nome='Beira'").fetchone()
    r = anonimo.get('/organizacoes', query_string={'provincia': 'Sofala', 'distrito': 'Beira'})
    assert r.status_code == 200
    n = db.execute("""SELECT COUNT(DISTINCT o.id) FROM ongs o JOIN ong_distritos od ON od.ong_id=o.id
                      WHERE od.distrito_id=? AND o.aprovacao='Aprovado' AND o.rascunho=0""", (d['id'],)).fetchone()[0]
    assert n > 0 and f'{n}' in texto(r)


# ── classificação completa de rotas ────────────────────────────────────────
PUBLICAS = {'login', 'login_2fa', 'logout', 'saude', 'inicio', 'noticias_lista', 'noticia_detalhe', 'chatbot_perguntar',
            'index', 'organizacoes', 'dashboard', 'levantamento_nacional', 'sector', 'detalhe', 'static',
            'ver_logo', 'logo_ong', 'api_chatbot', 'sobre', 'mapa_geojson'}


def _url(rule):
    u = rule.rule
    u = re.sub(r'<int:\w+>', '1', u)
    u = re.sub(r'<(?:path:)?\w+>', 'x', u)
    return u


def test_toda_a_rota_interna_exige_login(anonimo):
    """Falha se alguém acrescentar uma rota nova sem protecção nem a declarar pública."""
    from app import app
    desprotegidas = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint in PUBLICAS or rule.endpoint.startswith('api'):
            continue
        for metodo in rule.methods & {'GET', 'POST'}:
            url = _url(rule)
            r = anonimo.get(url) if metodo == 'GET' else anonimo.post(url)
            if r.status_code not in (302, 401, 403):
                desprotegidas.append((rule.endpoint, metodo, r.status_code))
    assert not desprotegidas, f'Rotas acessíveis sem login (declare-as públicas ou proteja-as): {desprotegidas}'


ROTAS_POST_RESTRITAS = [
    ('/admin/noticias/nova', {'titulo': 'Notícia Ilegal', 'resumo': 'x', 'corpo': 'y'}, {'super_admin', 'admin'}),
    ('/utilizadores/novo', {'email': 'novo@x.mz', 'nome_completo': 'N', 'senha': 'Abcdefgh1234', 'perfil': 'consulta'}, {'super_admin', 'admin'}),
]


@pytest.mark.parametrize('perfil', PERFIS)
@pytest.mark.parametrize('rota,dados,permitidos', ROTAS_POST_RESTRITAS)
def test_post_restrito_por_perfil(perfil, rota, dados, permitidos, db):
    c = cliente_com(perfil, 'Sofala' if perfil == 'gestor_provincial' else None)
    n_not = db.execute('SELECT COUNT(*) FROM noticias').fetchone()[0]
    n_utl = db.execute('SELECT COUNT(*) FROM utilizadores').fetchone()[0]
    c.post(rota, dados)
    mudou = (db.execute('SELECT COUNT(*) FROM noticias').fetchone()[0] != n_not or
             db.execute('SELECT COUNT(*) FROM utilizadores').fetchone()[0] != n_utl)
    assert mudou == (perfil in permitidos), f'{perfil} em {rota}'


def test_so_administradores_alteram_capa_e_gerem_contas_de_outros(db):
    alvo = criar_conta('operador', email='alvo@x.mz')
    uid = db.execute("SELECT id FROM utilizadores WHERE email=?", (alvo,)).fetchone()[0]
    for perfil in ('gestor_nacional', 'gestor_provincial', 'operador', 'consulta'):
        c = cliente_com(perfil, 'Sofala' if perfil == 'gestor_provincial' else None)
        c.post(f'/utilizadores/{uid}/email', {'email': 'roubado@x.mz'})
        c.post(f'/utilizadores/{uid}/repor-senha')
        c.post(f'/utilizadores/{uid}/desactivar')
        c.post('/admin/capa', {'remover': '1'})
    linha = db.execute('SELECT email, activo FROM utilizadores WHERE id=?', (uid,)).fetchone()
    assert linha['email'] == 'alvo@x.mz' and linha['activo'] == 1
    assert db.execute("SELECT valor FROM configuracoes WHERE chave='capa_inicio'").fetchone() is None


# ── uploads ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize('nome', ['x.html', 'x.php', 'x.svg', 'x.exe', 'x.jpg.html'])
def test_upload_de_capa_recusa_ficheiros_perigosos(super_admin, db, nome):
    super_admin.post('/admin/capa', {'imagem': (io.BytesIO(b'<script>alert(1)</script>'), nome)},
                     content_type='multipart/form-data')
    assert db.execute("SELECT valor FROM configuracoes WHERE chave='capa_inicio'").fetchone() is None


# ── publicação ─────────────────────────────────────────────────────────────
def test_build_do_render_nao_importa_dados():
    import os
    y = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'render.yaml'), encoding='utf-8').read()
    build = re.search(r'buildCommand:\s*"([^"]*)"', y).group(1)
    assert 'importar' not in build
    assert 'SGIONGS_PRODUCAO' in y and 'disk:' in y


# ── recuperação de emergência ──────────────────────────────────────────────
def test_recuperar_conta_super_admin_bloqueado_sem_2fa(db):
    import recuperar_conta
    email = criar_conta('super_admin', email='chefe@x.mz')
    db.execute("UPDATE utilizadores SET totp_secret='ABC', totp_ativo=1, activo=0 WHERE email=?", (email,))
    db.commit()
    c = Cliente('10.7.7.7')
    for _ in range(6):
        c.login(email, 'errada')
    assert recuperar_conta.recuperar('inexistente@x.mz') is None
    nova = recuperar_conta.recuperar(email.upper(), desligar_2fa=True)
    assert nova and len(nova) >= 10
    l = db.execute('SELECT activo, totp_ativo, deve_mudar_senha FROM utilizadores WHERE email=?', (email,)).fetchone()
    assert (l['activo'], l['totp_ativo'], l['deve_mudar_senha']) == (1, 0, 1)
    assert Cliente('10.7.7.8').login(email, nova).status_code == 302
    assert db.execute("SELECT COUNT(*) FROM historico_auditoria WHERE accao='repor_senha'").fetchone()[0] >= 1


# ── notícias iniciais com imagem ───────────────────────────────────────────
def test_noticias_iniciais_tem_imagem_que_existe_e_aparece(anonimo, db):
    import os
    import noticias_iniciais
    from conftest import RAIZ
    linhas = db.execute("SELECT titulo, imagem_url FROM noticias WHERE criado_por='sistema'").fetchall()
    assert len(linhas) == 3
    for l in linhas:
        assert l['imagem_url'], l['titulo']
        assert os.path.getsize(os.path.join(RAIZ, l['imagem_url'].lstrip('/'))) > 10_000
    html = texto(anonimo.get('/')) + texto(anonimo.get('/noticias'))
    for l in linhas:
        assert l['imagem_url'] in html
    assert anonimo.get(linhas[0]['imagem_url']).status_code == 200


def test_completar_imagens_nao_substitui_a_do_administrador(db):
    import noticias_iniciais
    db.execute("UPDATE noticias SET imagem_url = NULL")
    db.execute("UPDATE noticias SET imagem_url = '/static/uploads/minha.jpg' WHERE id = (SELECT MIN(id) FROM noticias)")
    db.commit()
    noticias_iniciais.completar_imagens(db)
    urls = [r[0] for r in db.execute('SELECT imagem_url FROM noticias ORDER BY id')]
    assert urls[0] == '/static/uploads/minha.jpg' and all(urls[1:])
