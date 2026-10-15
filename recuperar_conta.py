"""
recuperar_conta.py — Recuperação de emergência de uma conta (corre no servidor).

Uso:  python recuperar_conta.py <e-mail> [--sem-2fa]

Gera uma senha temporária (mostrada UMA vez), obriga a mudá-la no primeiro acesso,
desbloqueia a conta, reactiva-a se estava desactivada e, com --sem-2fa, desliga o
2FA. Fica registado na auditoria. Serve sobretudo quando o único Super
Administrador perdeu o acesso; nos restantes casos use /utilizadores.
"""
import sys
from werkzeug.security import generate_password_hash

import auditoria
import contas_iniciais
import login_guard
from database import get_connection, init_db


def recuperar(email, desligar_2fa=False):
    init_db()
    conn = get_connection()
    try:
        u = conn.execute('SELECT * FROM utilizadores WHERE lower(email) = lower(?) OR lower(username) = lower(?)',
                         (email, email)).fetchone()
        if not u:
            return None
        senha = contas_iniciais.gerar_senha(12)
        conn.execute('UPDATE utilizadores SET password_hash = ?, deve_mudar_senha = 1, activo = 1 WHERE id = ?',
                     (generate_password_hash(senha), u['id']))
        if desligar_2fa:
            conn.execute('UPDATE utilizadores SET totp_secret = NULL, totp_ativo = 0, totp_ultimo_passo = NULL WHERE id = ?', (u['id'],))
            conn.execute('DELETE FROM codigos_recuperacao_2fa WHERE utilizador_id = ?', (u['id'],))
        login_guard.limpar_conta(conn, u['username'])
        auditoria.registar(conn, 'repor_senha', f'Recuperação de emergência da conta {u["username"]} (linha de comandos)',
                           utilizador='servidor', detalhes={'desligar_2fa': desligar_2fa})
        conn.commit()
        return senha
    finally:
        conn.close()


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if len(args) != 1:
        print(__doc__)
        sys.exit(2)
    s = recuperar(args[0], '--sem-2fa' in sys.argv)
    if s is None:
        print('Conta não encontrada.')
        sys.exit(1)
    print(f'Senha temporária para {args[0]}: {s}\nGuarde-a agora; será obrigatório mudá-la no primeiro acesso.')
