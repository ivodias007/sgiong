"""
seguranca.py — Política de senha e 2FA (TOTP) do SGIONGs.

2FA só está disponível para contas reais criadas em /utilizadores (tabela
`utilizadores`) — as duas contas legadas por variável de ambiente
(superadmin/admin) não têm registo na base de dados para guardar o
segredo TOTP, o que é mais uma razão para migrar para contas reais.
"""

import hashlib
import io
import re
import secrets
import time

import pyotp
import qrcode


def senha_e_forte(senha):
    """Política mínima: 10+ caracteres, pelo menos uma letra e um número.
    Devolve (True, '') ou (False, 'motivo')."""
    if len(senha) < 10:
        return False, 'A senha deve ter pelo menos 10 caracteres.'
    if not re.search(r'[A-Za-z]', senha):
        return False, 'A senha deve incluir pelo menos uma letra.'
    if not re.search(r'[0-9]', senha):
        return False, 'A senha deve incluir pelo menos um número.'
    return True, ''


def gerar_segredo_totp():
    return pyotp.random_base32()


def uri_provisionamento(segredo, username, emissor='SGIONGs'):
    return pyotp.TOTP(segredo).provisioning_uri(name=username, issuer_name=emissor)


def verificar_codigo_totp(segredo, codigo):
    if not segredo or not codigo:
        return False
    try:
        return pyotp.TOTP(segredo).verify(codigo.strip(), valid_window=1)
    except (ValueError, TypeError):
        return False


def gerar_qrcode_png(uri):
    """Devolve os bytes PNG do QR code, para servir directamente numa rota
    Flask sem gravar ficheiros em disco."""
    imagem = qrcode.make(uri)
    buffer = io.BytesIO()
    imagem.save(buffer, format='PNG')
    buffer.seek(0)
    return buffer.getvalue()


def passo_totp_valido(segredo, codigo, ultimo_passo=None):
    """Devolve o 'passo' de 30 s em que o código é válido, ou None. Recusa passos
    já usados (ultimo_passo) — um código roubado/observado não pode ser repetido."""
    if not segredo or not codigo or not re.fullmatch(r'\d{6}', codigo.strip()):
        return None
    totp = pyotp.TOTP(segredo)
    agora = int(time.time() // 30)
    for passo in (agora - 1, agora, agora + 1):
        if secrets.compare_digest(totp.at(passo * 30), codigo.strip()):
            if ultimo_passo is not None and passo <= ultimo_passo:
                return None
            return passo
    return None


# ── códigos de recuperação do 2FA ────────────────────────────────────────────
_ALFABETO = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'


def _hash(texto):
    return hashlib.sha256(texto.encode('utf-8')).hexdigest()


def normalizar_codigo_recuperacao(codigo):
    return re.sub(r'[^A-Z0-9]', '', (codigo or '').upper())


def gerar_codigos_recuperacao(conn, utilizador_id, quantidade=10):
    """Substitui os códigos anteriores por `quantidade` novos (formato XXXXX-XXXXX,
    ~50 bits cada). Devolve-os em claro UMA vez; na base fica só o hash."""
    conn.execute('DELETE FROM codigos_recuperacao_2fa WHERE utilizador_id = ?', (utilizador_id,))
    codigos = []
    for _ in range(quantidade):
        bruto = ''.join(secrets.choice(_ALFABETO) for _ in range(10))
        conn.execute('INSERT INTO codigos_recuperacao_2fa (utilizador_id, codigo_hash) VALUES (?, ?)',
                     (utilizador_id, _hash(bruto)))
        codigos.append(f'{bruto[:5]}-{bruto[5:]}')
    return codigos


def consumir_codigo_recuperacao(conn, utilizador_id, codigo):
    """True (e queima o código) se `codigo` for um código de recuperação válido e por usar."""
    bruto = normalizar_codigo_recuperacao(codigo)
    if len(bruto) != 10:
        return False
    cur = conn.execute("""UPDATE codigos_recuperacao_2fa SET usado_em = datetime('now')
                          WHERE utilizador_id = ? AND codigo_hash = ? AND usado_em IS NULL""",
                       (utilizador_id, _hash(bruto)))
    return cur.rowcount == 1


def codigos_restantes(conn, utilizador_id):
    return conn.execute('SELECT COUNT(*) FROM codigos_recuperacao_2fa WHERE utilizador_id = ? AND usado_em IS NULL',
                        (utilizador_id,)).fetchone()[0]


# ── recuperação de senha por e-mail ──────────────────────────────────────────
VALIDADE_RESET_SEGUNDOS = 30 * 60


def criar_token_reset(conn, utilizador_id, ip=None):
    """Invalida pedidos anteriores e devolve um token novo (só o hash fica guardado)."""
    conn.execute("UPDATE reset_senha_tokens SET usado_em = datetime('now') WHERE utilizador_id = ? AND usado_em IS NULL",
                 (utilizador_id,))
    token = secrets.token_urlsafe(32)
    conn.execute('INSERT INTO reset_senha_tokens (utilizador_id, token_hash, expira_em, ip) VALUES (?, ?, ?, ?)',
                 (utilizador_id, _hash(token), time.time() + VALIDADE_RESET_SEGUNDOS, ip))
    return token


def token_reset_valido(conn, token):
    """Linha do token (com utilizador_id) se existir, não expirou e não foi usado; senão None."""
    if not token or len(token) > 100:
        return None
    return conn.execute('SELECT * FROM reset_senha_tokens WHERE token_hash = ? AND usado_em IS NULL AND expira_em > ?',
                        (_hash(token), time.time())).fetchone()


def queimar_token_reset(conn, token_id):
    conn.execute("UPDATE reset_senha_tokens SET usado_em = datetime('now') WHERE id = ?", (token_id,))
