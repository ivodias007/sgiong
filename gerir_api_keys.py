#!/usr/bin/env python3
"""
gerir_api_keys.py — Criar, listar e revogar chaves de acesso à API.

A chave em si só é mostrada UMA VEZ, no momento da criação — só o hash fica
guardado na base de dados (tal como as palavras-passe dos utilizadores).

USO
---
  python gerir_api_keys.py criar "Nome da integração (ex.: Portal de Dados Abertos MPD)"
  python gerir_api_keys.py listar
  python gerir_api_keys.py revogar <id>
"""

import sys
import secrets
from werkzeug.security import generate_password_hash

from database import get_connection

SQL_CRIAR_TABELA = '''
CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome_integracao TEXT NOT NULL,
    chave_hash TEXT NOT NULL,
    activa INTEGER NOT NULL DEFAULT 1,
    criado_em TEXT NOT NULL DEFAULT (datetime('now'))
);
'''


def garantir_tabela(conn):
    conn.execute(SQL_CRIAR_TABELA)
    conn.commit()


def criar(nome_integracao):
    conn = get_connection()
    garantir_tabela(conn)

    chave = secrets.token_urlsafe(32)
    chave_hash = generate_password_hash(chave)  # scrypt, tal como as passwords dos utilizadores

    cur = conn.execute(
        'INSERT INTO api_keys (nome_integracao, chave_hash) VALUES (?, ?)',
        (nome_integracao, chave_hash)
    )
    conn.commit()
    novo_id = cur.lastrowid
    conn.close()

    print(f'Chave criada para "{nome_integracao}" (id={novo_id}).')
    print()
    print('GUARDE ESTA CHAVE AGORA — não será mostrada novamente:')
    print(f'  {chave}')
    print()
    print('Uso no pedido HTTP:')
    print(f'  curl -H "X-API-Key: {chave}" https://<o-vosso-dominio>/api/v1/ongs')


def listar():
    conn = get_connection()
    garantir_tabela(conn)
    linhas = conn.execute('SELECT id, nome_integracao, activa, criado_em FROM api_keys ORDER BY id').fetchall()
    conn.close()

    if not linhas:
        print('Nenhuma chave de API criada ainda.')
        return

    for l in linhas:
        estado = 'ACTIVA' if l['activa'] else 'REVOGADA'
        print(f"  [{l['id']}] {l['nome_integracao']} — {estado} — criada em {l['criado_em']}")


def revogar(id_chave):
    conn = get_connection()
    garantir_tabela(conn)
    conn.execute('UPDATE api_keys SET activa = 0 WHERE id = ?', (id_chave,))
    conn.commit()
    conn.close()
    print(f'Chave {id_chave} revogada.')


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    comando = sys.argv[1]
    if comando == 'criar' and len(sys.argv) >= 3:
        criar(' '.join(sys.argv[2:]))
    elif comando == 'listar':
        listar()
    elif comando == 'revogar' and len(sys.argv) >= 3:
        revogar(int(sys.argv[2]))
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == '__main__':
    main()
