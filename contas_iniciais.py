"""contas_iniciais.py — Cria as 11 contas de Gestor Provincial (uma por província).

Nunca duplica: se a província já tem Gestor Provincial, é ignorada. Cada conta
tem o e-mail como utilizador de entrada e obriga a mudar a palavra-passe no
primeiro acesso.

Uso na linha de comandos:   python contas_iniciais.py [dominio_do_email]
Também disponível no ecrã de Utilizadores (botão "Criar as 11 contas provinciais").
"""
import re
import secrets
import sys
import unicodedata

from werkzeug.security import generate_password_hash

from database import get_connection, init_db
from tagging import PROVINCIAS

DOMINIO_PADRAO = 'sgiong.mpd.gov.mz'


def _slug(texto):
    t = unicodedata.normalize('NFKD', texto.lower())
    t = ''.join(c for c in t if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]+', '-', t).strip('-')


def email_gestor(provincia, dominio=DOMINIO_PADRAO):
    return f'gestor.{_slug(provincia)}@{dominio}'


def gerar_senha(tamanho=12):
    """Palavra-passe aleatória legível (sem caracteres ambíguos), com letra e número."""
    alfabeto = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'
    while True:
        s = ''.join(secrets.choice(alfabeto) for _ in range(tamanho))
        if re.search(r'[A-Za-z]', s) and re.search(r'[0-9]', s):
            return s


def criar_gestores_provinciais(conn, dominio=DOMINIO_PADRAO, criado_por='sistema'):
    """Devolve (criadas, ignoradas): criadas = lista de dicts com
    provincia/email/senha (a senha só existe aqui — na base fica o hash)."""
    criadas, ignoradas = [], []
    for provincia in PROVINCIAS:
        ja = conn.execute("SELECT 1 FROM utilizadores WHERE perfil='gestor_provincial' AND provincia=?",
                          (provincia,)).fetchone()
        email = email_gestor(provincia, dominio)
        if ja or conn.execute('SELECT 1 FROM utilizadores WHERE lower(email)=? OR username=?',
                              (email, email)).fetchone():
            ignoradas.append(provincia)
            continue
        senha = gerar_senha()
        conn.execute('''INSERT INTO utilizadores (username, email, nome_completo, password_hash, perfil, provincia,
                        criado_por, deve_mudar_senha) VALUES (?,?,?,?,?,?,?,1)''',
                     (email, email, f'Gestor Provincial — {provincia}', generate_password_hash(senha),
                      'gestor_provincial', provincia, criado_por))
        criadas.append({'provincia': provincia, 'email': email, 'senha': senha})
    return criadas, ignoradas


if __name__ == '__main__':
    init_db()
    dominio = sys.argv[1] if len(sys.argv) > 1 else DOMINIO_PADRAO
    conn = get_connection()
    criadas, ignoradas = criar_gestores_provinciais(conn, dominio)
    conn.commit()
    conn.close()
    print(f'{len(criadas)} conta(s) criada(s); {len(ignoradas)} província(s) já tinham gestor.\n')
    for c in criadas:
        print(f'{c["provincia"]:<18} {c["email"]:<48} {c["senha"]}')
    if criadas:
        print('\nGuarde estas palavras-passe agora — não voltam a ser mostradas. '
              'Cada gestor tem de a mudar no primeiro acesso.')
