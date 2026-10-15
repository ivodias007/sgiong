"""
login_guard.py — Bloqueio persistente contra tentativas repetidas de login.

Conta falhas por IP e por conta (e-mail/utilizador) na tabela login_tentativas,
por isso sobrevivem a reinícios e funcionam com mais de um processo. Uma conta
é bloqueada após LIMITE_CONTA falhas em JANELA segundos; um IP após LIMITE_IP.
O bloqueio da conta impede também ataques distribuídos (muitos IPs, uma conta).
"""
import time

LIMITE_CONTA = 5
LIMITE_IP = 20
JANELA = 900  # 15 minutos


def _chave_conta(conta):
    return 'conta:' + (conta or '').strip().lower()


def _contar(conn, chave):
    limite = time.time() - JANELA
    return conn.execute('SELECT COUNT(*) FROM login_tentativas WHERE chave = ? AND momento > ?',
                        (chave, limite)).fetchone()[0]


def bloqueado(conn, ip, conta):
    return (_contar(conn, 'ip:' + (ip or '?')) >= LIMITE_IP or
            _contar(conn, _chave_conta(conta)) >= LIMITE_CONTA)


def registar_falha(conn, ip, conta):
    agora = time.time()
    conn.executemany('INSERT INTO login_tentativas (chave, momento) VALUES (?, ?)',
                     [('ip:' + (ip or '?'), agora), (_chave_conta(conta), agora)])
    conn.execute('DELETE FROM login_tentativas WHERE momento < ?', (agora - 24 * 3600,))
    conn.commit()


def limpar_conta(conn, conta):
    conn.execute('DELETE FROM login_tentativas WHERE chave = ?', (_chave_conta(conta),))
    conn.commit()
