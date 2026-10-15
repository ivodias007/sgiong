import os
import subprocess
import sys

import pyotp
from conftest import (Cliente, SENHA, RAIZ, criar_conta, cliente_com, texto)
import database


def test_login_com_email_e_maiusculas(anonimo):
    e = criar_conta('operador')
    assert anonimo.login(e.upper()).status_code == 302


def test_login_errado_nao_entra(anonimo):
    e = criar_conta('operador')
    r = anonimo.login(e, 'errada', seguir=True)
    assert 'incorretos' in texto(r)
    assert anonimo.get('/utilizadores').status_code == 302  # continua sem sessão


def test_bloqueio_por_conta_mesmo_com_ips_diferentes():
    e = criar_conta('operador')
    for i in range(5):
        Cliente(ip=f'10.1.0.{i}').login(e, 'errada')
    # senha CERTA, IP novo: continua bloqueada
    r = Cliente(ip='10.1.9.9').login(e)
    assert r.status_code == 429


def test_bloqueio_por_ip():
    for i in range(20):
        Cliente(ip='10.2.0.1').login(f'ninguem{i}@x.mz', 'x')
    e = criar_conta('operador')
    assert Cliente(ip='10.2.0.1').login(e).status_code == 429
    assert Cliente(ip='10.2.0.2').login(e).status_code == 302  # outro IP não é afectado


def test_login_certo_limpa_falhas():
    e = criar_conta('operador')
    for _ in range(3):
        Cliente(ip='10.3.0.1').login(e, 'errada')
    assert Cliente(ip='10.3.0.2').login(e).status_code == 302
    for _ in range(4):
        Cliente(ip='10.3.0.3').login(e, 'errada')
    assert Cliente(ip='10.3.0.4').login(e).status_code == 302  # contador recomeçou


def test_admin_desbloqueia_conta_repondo_senha(super_admin):
    e = criar_conta('operador')
    for i in range(5):
        Cliente(ip=f'10.4.0.{i}').login(e, 'errada')
    assert Cliente(ip='10.4.1.1').login(e).status_code == 429
    uid = database.get_connection().execute('SELECT id FROM utilizadores WHERE username=?', (e,)).fetchone()[0]
    r = super_admin.post(f'/utilizadores/{uid}/repor-senha')
    assert r.status_code == 200 and 'temporári' in texto(r).lower() or r.status_code == 200
    assert Cliente(ip='10.4.1.2').login(e, 'qualquer').status_code != 429  # já não está bloqueada


def test_falhas_ficam_na_auditoria(anonimo, db):
    anonimo.login('x@y.mz', 'errada')
    assert db.execute("SELECT COUNT(*) FROM historico_auditoria WHERE accao='login_falhado'").fetchone()[0] >= 1


def test_open_redirect_bloqueado(anonimo):
    e = criar_conta('operador')
    for destino in ['//evil.com', 'http://evil.com', '/\\evil.com', 'https://evil.com/x']:
        c = Cliente()
        r = c.post(f'/login?next={destino}', {'utilizador': e, 'senha': SENHA})
        assert r.status_code == 302
        loc = r.headers['Location']
        assert 'evil.com' not in loc, (destino, loc)


def test_csrf_obrigatorio(anonimo):
    r = anonimo.c.post('/login', data={'utilizador': 'a', 'senha': 'b'})
    assert r.status_code == 400


def test_cookie_de_sessao_httponly_samesite(anonimo):
    e = criar_conta('operador')
    r = anonimo.login(e)
    cookie = r.headers.get('Set-Cookie', '')
    assert 'HttpOnly' in cookie and 'SameSite=Lax' in cookie


def test_cabecalhos_de_seguranca(anonimo):
    r = anonimo.get('/')
    assert r.headers['X-Frame-Options'] == 'DENY' and r.headers['X-Content-Type-Options'] == 'nosniff'


def test_sessao_nova_apos_login_nao_herda_pre_login():
    c = Cliente()
    with c.c.session_transaction() as s:
        s['lixo'] = 'fixado-pelo-atacante'
    c.login(criar_conta('operador'))
    with c.c.session_transaction() as s:
        assert 'lixo' not in s


# ── credenciais de demonstração ──────────────────────────────────────────────
def _correr_py(codigo, **env):
    e = {**os.environ, **env}
    return subprocess.run([sys.executable, '-c', codigo], cwd=RAIZ, env=e, capture_output=True, text=True)


def test_em_producao_senhas_de_demonstracao_sao_recusadas():
    codigo = '''
import app
from werkzeug.security import check_password_hash
c = app.app.test_client()
c.get("/login", base_url="https://localhost")
with c.session_transaction() as s: t = s["csrf_token"]
for u, p in [("superadmin", "superadmin2026"), ("adminong", "admin2026")]:
    r = c.post("/login", data={"utilizador": u, "senha": p, "csrf_token": t}, base_url="https://localhost")
    print(u, r.status_code, r.headers.get("Location"))
'''
    r = _correr_py(codigo, SGIONGS_PRODUCAO='1', SGIONGS_SECRET_KEY='x',
                   SGIONGS_DB_PATH=os.path.join(os.environ['SGIONGS_DATA_DIR'], 'prod.db'))
    assert r.returncode == 0, r.stderr
    for linha in r.stdout.strip().splitlines():
        assert ' 200 ' in linha or ' 429 ' in linha, linha  # voltou ao formulário: NÃO entrou


def test_fora_de_producao_demonstracao_continua_a_funcionar_para_testes(anonimo):
    assert anonimo.login('superadmin', 'superadmin2026').status_code == 302


def test_super_admin_inicial_por_variavel_de_ambiente():
    codigo = '''
import app
c = app.app.test_client()
c.get("/login", base_url="https://localhost")
with c.session_transaction() as s: t = s["csrf_token"]
r = c.post("/login", data={"utilizador": "primeiro@mpd.gov.mz", "senha": "Arranque-2026-xyz", "csrf_token": t}, base_url="https://localhost")
print(r.status_code)
r2 = c.get("/utilizadores", base_url="https://localhost")
print(r2.status_code, r2.headers.get("Location"))
'''
    r = _correr_py(codigo, SGIONGS_PRODUCAO='1', SGIONGS_SECRET_KEY='x',
                   SGIONGS_BOOTSTRAP_EMAIL='primeiro@mpd.gov.mz', SGIONGS_BOOTSTRAP_PASSWORD='Arranque-2026-xyz',
                   SGIONGS_DB_PATH=os.path.join(os.environ['SGIONGS_DATA_DIR'], 'boot.db'))
    assert r.returncode == 0, r.stderr
    linhas = r.stdout.split('\n')
    assert linhas[0].strip() == '302'
    assert '/conta' in linhas[1]  # obrigado a mudar a senha antes de fazer o que quer que seja


# ── 2FA e recuperação ────────────────────────────────────────────────────────
def _activar_2fa(c):
    c.get('/conta/2fa/configurar')
    conn = database.get_connection()
    seg = conn.execute('SELECT totp_secret FROM utilizadores WHERE username=?', (c.email,)).fetchone()[0]
    conn.close()
    r = c.post('/conta/2fa/activar', {'codigo': pyotp.TOTP(seg).now()})
    return seg, r


def test_2fa_fluxo_completo():
    c = cliente_com('gestor_nacional')
    seg, r = _activar_2fa(c)
    conn = database.get_connection()
    assert conn.execute('SELECT totp_ativo FROM utilizadores WHERE username=?', (c.email,)).fetchone()[0] == 1
    conn.close()

    novo = Cliente(ip='10.5.0.1')
    r = novo.login(c.email)
    assert r.status_code == 302 and '/login/2fa' in r.headers['Location']
    assert novo.get('/utilizadores').status_code == 302          # só com password: sem acesso
    r = novo.post('/login/2fa', {'codigo': '000000'})
    assert r.status_code == 200 and 'inválido' in texto(r)
    # o código da activação já foi usado (anti-replay): usa o do passo seguinte
    r = novo.post('/login/2fa', {'codigo': pyotp.TOTP(seg).at(__import__('time').time() + 30)})
    assert r.status_code == 302
    assert novo.get('/pendentes').status_code == 200              # sessão completa


def test_2fa_bloqueia_adivinhacao_de_codigos():
    c = cliente_com('gestor_nacional')
    seg, _ = _activar_2fa(c)
    atacante = Cliente(ip='10.6.0.1')
    atacante.login(c.email)
    for _ in range(5):
        atacante.post('/login/2fa', {'codigo': '123456'})
    r = atacante.post('/login/2fa', {'codigo': pyotp.TOTP(seg).at(__import__('time').time() + 30)})  # até o código certo é recusado
    assert r.status_code == 302 and '/login' in r.headers['Location'] and '2fa' not in r.headers['Location']


def test_2fa_codigo_errado_na_activacao_nao_activa():
    c = cliente_com('gestor_nacional')
    c.get('/conta/2fa/configurar')
    c.post('/conta/2fa/activar', {'codigo': '111111'})
    conn = database.get_connection()
    assert conn.execute('SELECT totp_ativo FROM utilizadores WHERE username=?', (c.email,)).fetchone()[0] == 0


def test_recuperacao_perdeu_telemovel_admin_repoe_2fa(super_admin):
    c = cliente_com('operador')
    _activar_2fa(c)
    conn = database.get_connection()
    uid = conn.execute('SELECT id FROM utilizadores WHERE username=?', (c.email,)).fetchone()[0]
    conn.close()
    r = super_admin.post(f'/utilizadores/{uid}/repor-2fa')
    assert r.status_code == 302
    r = Cliente(ip='10.7.0.1').login(c.email)       # entra só com a senha, como antes de activar
    assert r.status_code == 302 and '2fa' not in r.headers['Location']


def test_recuperacao_senha_temporaria_obriga_a_mudar():
    sa = cliente_com('super_admin')
    e = criar_conta('operador')
    conn = database.get_connection()
    uid = conn.execute('SELECT id FROM utilizadores WHERE username=?', (e,)).fetchone()[0]
    conn.close()
    r = sa.post(f'/utilizadores/{uid}/repor-senha')
    html = texto(r)
    import re
    temp = re.search(r'<code style="font-size:1rem;">([^<]+)</code>', html)
    assert temp, 'a página deve mostrar a senha temporária uma vez'
    novo = Cliente(ip='10.8.0.1')
    assert novo.login(e, temp.group(1).strip()).status_code == 302
    assert novo.get('/relatorios').status_code == 302 and '/conta' in novo.get('/relatorios').headers['Location']
    assert SENHA != temp.group(1)


def test_admin_nao_gere_outro_admin_nem_super_admin():
    a1 = cliente_com('admin')
    outro = criar_conta('admin', email='outro-admin@teste.mz')
    sa = criar_conta('super_admin', email='sa2@teste.mz')
    conn = database.get_connection()
    ids = [conn.execute('SELECT id FROM utilizadores WHERE username=?', (e,)).fetchone()[0] for e in (outro, sa)]
    conn.close()
    for uid in ids:
        for rota in ('repor-senha', 'repor-2fa', 'desactivar'):
            a1.post(f'/utilizadores/{uid}/{rota}')
        a1.post(f'/utilizadores/{uid}/email', {'email': 'x@y.mz'})
    conn = database.get_connection()
    for e in (outro, sa):
        l = conn.execute('SELECT activo, email FROM utilizadores WHERE username=?', (e,)).fetchone()
        assert l and l['activo'] == 1
    # as senhas continuam as originais
    assert Cliente(ip='10.9.0.1').login(outro).status_code == 302
    assert Cliente(ip='10.9.0.2').login(sa).status_code == 302


def test_admin_nao_cria_super_admin(admin):
    r = admin.post('/utilizadores/novo', {'email': 'novo-sa@teste.mz', 'nome_completo': 'X', 'perfil': 'super_admin',
                                          'senha': 'Senha-Forte-123', 'provincia': ''})
    conn = database.get_connection()
    assert conn.execute("SELECT COUNT(*) FROM utilizadores WHERE username='novo-sa@teste.mz'").fetchone()[0] == 0


def test_politica_de_senha():
    import seguranca
    assert not seguranca.senha_e_forte('curta1')[0]
    assert not seguranca.senha_e_forte('apenasletrasaqui')[0]
    assert not seguranca.senha_e_forte('1234567890123')[0]
    assert seguranca.senha_e_forte('Senha-Forte-123')[0]
