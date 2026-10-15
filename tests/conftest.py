"""Fixtures dos testes do SGIONGs.

Usam uma base de dados TEMPORÁRIA semeada a partir dos CSV reais (data/*.csv),
copiada de novo antes de cada teste — nunca tocam em data/ongs.db.
Correr:  pytest -q
"""
import os
import re
import shutil
import sys
import tempfile

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

_TMP = tempfile.mkdtemp(prefix='sgiongs_teste_')
os.environ['SGIONGS_DATA_DIR'] = _TMP
os.environ['SGIONGS_DB_PATH'] = os.path.join(_TMP, 'ongs.db')
os.environ['SGIONGS_SECRET_KEY'] = 'chave-de-teste'
os.environ.pop('SGIONGS_PRODUCAO', None)
os.environ.pop('SGIONGS_BACKUP_EXTRA_DIR', None)

import database  # noqa: E402
import app as app_modulo  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

app_modulo.app.config['TESTING'] = True
app_modulo.app.config['PROPAGATE_EXCEPTIONS'] = False

SENHA = 'Senha-Teste-2026'
_MODELO = os.path.join(_TMP, 'modelo.db')


@pytest.fixture(scope='session', autouse=True)
def _base_modelo():
    """Importa os CSV reais uma só vez e guarda uma cópia-modelo."""
    import importar_dados
    importar_dados.importar(os.path.join(RAIZ, 'data'), substituir=True)
    shutil.copy2(database.DB_PATH, _MODELO)
    yield
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture(autouse=True)
def bd_limpa(_base_modelo):
    """Repõe a base de dados do modelo antes de cada teste."""
    for suf in ('', '-wal', '-shm'):
        try:
            os.remove(database.DB_PATH + suf)
        except FileNotFoundError:
            pass
    shutil.copy2(_MODELO, database.DB_PATH)
    pasta_bk = os.path.join(_TMP, 'backups')
    shutil.rmtree(pasta_bk, ignore_errors=True)
    yield


def criar_conta(perfil, provincia=None, email=None, deve_mudar=0, senha=SENHA):
    email = email or f'{perfil}{"-" + provincia.lower() if provincia else ""}@teste.mz'.replace(' ', '')
    conn = database.get_connection()
    conn.execute('''INSERT INTO utilizadores (username, email, nome_completo, password_hash, perfil, provincia, activo, deve_mudar_senha)
                    VALUES (?, ?, ?, ?, ?, ?, 1, ?)''',
                 (email, email, f'Teste {perfil}', generate_password_hash(senha), perfil, provincia, deve_mudar))
    conn.commit()
    conn.close()
    return email


class Cliente:
    """Cliente de testes com login e CSRF automáticos."""

    def __init__(self, ip='10.0.0.1'):
        self.c = app_modulo.app.test_client()
        self.ip = ip

    def _env(self):
        return {'REMOTE_ADDR': self.ip}

    def get(self, url, **kw):
        return self.c.get(url, environ_overrides=self._env(), **kw)

    def token(self):
        with self.c.session_transaction() as s:
            if 'csrf_token' not in s:
                s['csrf_token'] = 'tok-teste'
            return s['csrf_token']

    def post(self, url, data=None, **kw):
        d = dict(data or {})
        d.setdefault('csrf_token', self.token())
        return self.c.post(url, data=d, environ_overrides=self._env(), **kw)

    def login(self, email, senha=SENHA, seguir=False):
        return self.post('/login', {'utilizador': email, 'senha': senha}, follow_redirects=seguir)


def cliente_com(perfil, provincia=None, ip='10.0.0.1'):
    email = criar_conta(perfil, provincia)
    c = Cliente(ip)
    r = c.login(email)
    assert r.status_code == 302, f'login falhou para {perfil}'
    c.email = email
    return c


@pytest.fixture
def anonimo():
    return Cliente()


@pytest.fixture
def super_admin():
    return cliente_com('super_admin')


@pytest.fixture
def admin():
    return cliente_com('admin')


@pytest.fixture
def db():
    conn = database.get_connection()
    yield conn
    conn.close()


def texto(resp):
    return resp.get_data(as_text=True)


def primeiro_id(db, aprovacao='Aprovado', provincia=None):
    q = "SELECT id FROM ongs WHERE aprovacao = ? AND rascunho = 0"
    p = [aprovacao]
    if provincia:
        q += ' AND provincia = ?'
        p.append(provincia)
    return db.execute(q + ' ORDER BY id LIMIT 1', p).fetchone()[0]
