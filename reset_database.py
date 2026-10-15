#!/usr/bin/env python3
"""
reset_database.py — Reset completo da base de dados do SGIONGs.

Corrige a versão anterior deste script, que tinha sido escrita antes de eu
conhecer o código real do projecto e assumia SQLAlchemy. Este usa o mesmo
mecanismo que o resto do sistema: sqlite3 puro, via database.py/schema.sql.

O QUE FAZ:
  1. Faz backup do ficheiro data/ongs.db actual (se existir)
  2. Apaga o ficheiro da base de dados
  3. Recria o schema vazio a partir de schema.sql (via init_db())
  4. NÃO recria as contas de utilizador — o sistema continua a aceitar as
     contas legadas definidas por variável de ambiente (ou os valores por
     defeito de desenvolvimento em config.py) para o primeiro login.

USO:
  python reset_database.py            # pede confirmação
  python reset_database.py --yes      # não pede confirmação
"""

import os
import sys
import shutil
from datetime import datetime

from database import DB_PATH, init_db


def main():
    auto_confirm = '--yes' in sys.argv

    print('=' * 60)
    print('RESET DA BASE DE DADOS — SGIONGs')
    print('=' * 60)
    print(f'Ficheiro: {DB_PATH}')
    print('Isto apaga TODAS as ONGs, utilizadores e histórico de auditoria.')
    print()

    if not auto_confirm:
        resposta = input("Tem a certeza? Escreva 'CONFIRMAR': ")
        if resposta.strip().upper() != 'CONFIRMAR':
            print('Cancelado.')
            return

    if os.path.exists(DB_PATH):
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = f'{DB_PATH}.backup_{timestamp}'
        shutil.copy2(DB_PATH, backup_path)
        print(f'Backup criado em: {backup_path}')
        os.remove(DB_PATH)

    init_db()
    print('Base de dados recriada, vazia.')
    print()
    print('Para ter dados, corra a seguir: python importar_dados.py')
    print('Para aceder, use as credenciais definidas em SGIONGS_ADMIN_PASSWORD_HASH /')
    print('SGIONGS_SUPERADMIN_PASSWORD_HASH, ou os valores de desenvolvimento em config.py')
    print('se essas variáveis não estiverem definidas.')


if __name__ == '__main__':
    main()
