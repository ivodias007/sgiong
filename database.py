import sqlite3
import os

from tagging import ESTRUTURA_AREAS_TEMATICAS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Pasta dos dados persistentes. Em produção aponte SGIONGS_DATA_DIR para o disco
# persistente (ex.: /var/data) — a base, os backups e os uploads ficam lá e
# sobrevivem a reinícios e novas publicações.
DATA_DIR = os.environ.get('SGIONGS_DATA_DIR') or os.path.join(BASE_DIR, 'data')
DB_PATH = os.environ.get('SGIONGS_DB_PATH') or os.path.join(DATA_DIR, 'ongs.db')
SCHEMA_PATH = os.path.join(BASE_DIR, 'schema.sql')


def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    conn.execute('PRAGMA busy_timeout = 30000')
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_connection()
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        conn.executescript(f.read())
    _migrar_colunas_novas(conn)
    _semear_taxonomia_fixa(conn)
    _preencher_dados_derivados(conn)
    conn.commit()
    conn.close()


def _migrar_colunas_novas(conn):
    """Acrescenta colunas novas a bases de dados criadas antes desta versão.
    'CREATE TABLE IF NOT EXISTS' não altera tabelas já existentes, por isso
    fazemos aqui as migrações de coluna, ignorando o erro se já existirem."""
    colunas_novas = [
        ('ongs', 'sigla', 'TEXT'),
        ('ongs', 'ano_entrada_pais', 'INTEGER'),
        ('ongs', 'logo_url', 'TEXT'),
        # Fase 3 — sub-estados do workflow (complementam aprovacao, não a substituem)
        ('ongs', 'rascunho', 'INTEGER NOT NULL DEFAULT 0'),
        ('ongs', 'fase_workflow', 'TEXT'),
        ('ongs', 'em_analise_por', 'TEXT'),
        ('ongs', 'em_analise_em', 'TEXT'),
        ('ongs', 'sinalizado_por', 'TEXT'),
        ('ongs', 'sinalizado_em', 'TEXT'),
        ('ongs', 'sinalizado_motivo', 'TEXT'),
        # Fase 7 — segurança (2FA)
        ('utilizadores', 'totp_secret', 'TEXT'),
        ('utilizadores', 'totp_ativo', 'INTEGER NOT NULL DEFAULT 0'),
        ('utilizadores', 'totp_ultimo_passo', 'INTEGER'),
        ('utilizadores', 'senha_alterada_em', 'TEXT'),
        ('utilizadores', 'email', 'TEXT'),
        ('utilizadores', 'deve_mudar_senha', 'INTEGER NOT NULL DEFAULT 0'),
    ]
    for tabela, coluna, tipo in colunas_novas:
        try:
            conn.execute(f'ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}')
        except sqlite3.OperationalError:
            pass  # coluna já existe
    # Unicidade: um e-mail só pode pertencer a uma conta, e cada província só
    # pode ter UM Gestor Provincial (impede contas duplicadas).
    for sql in (
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_utilizadores_email ON utilizadores(lower(email)) WHERE email IS NOT NULL AND email != ''",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_gestor_provincial_unico ON utilizadores(provincia) WHERE perfil = 'gestor_provincial'",
    ):
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass


def _preencher_dados_derivados(conn):
    """Preenche ong_provincias/ong_naturezas a partir dos campos antigos
    (provincia e natureza em texto simples) para organizações já existentes
    que ainda não têm estas tabelas povoadas — mantém a app compatível com
    bases de dados criadas antes de existirem estas tabelas."""
    orgs = conn.execute("SELECT id, provincia, natureza FROM ongs").fetchall()
    for o in orgs:
        if o['provincia']:
            conn.execute(
                'INSERT OR IGNORE INTO ong_provincias (ong_id, provincia) VALUES (?, ?)',
                (o['id'], o['provincia'])
            )
        if o['natureza']:
            for n in o['natureza'].split(','):
                n = n.strip()
                if n:
                    conn.execute(
                        'INSERT OR IGNORE INTO ong_naturezas (ong_id, natureza) VALUES (?, ?)',
                        (o['id'], n)
                    )


def _semear_taxonomia_fixa(conn):
    """Garante que as 8 áreas temáticas e as suas ramificações oficiais
    existem sempre na base de dados, mesmo antes de qualquer importação —
    para que apareçam nos filtros com 0 em vez de não aparecerem."""
    for area, ramificacoes in ESTRUTURA_AREAS_TEMATICAS.items():
        conn.execute('INSERT OR IGNORE INTO areas (nome) VALUES (?)', (area,))
        area_id = conn.execute('SELECT id FROM areas WHERE nome = ?', (area,)).fetchone()['id']
        for sub in ramificacoes:
            conn.execute('INSERT OR IGNORE INTO ramificacoes (nome, area_id) VALUES (?, ?)', (sub, area_id))
