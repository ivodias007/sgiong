# config.py
# Credenciais de acesso dos utilizadores do SGIONGs.
#
# Existem dois níveis de acesso:
#
#   ADMIN (Administrador)
#     - Pode registar novas ONGs (ficam "Pendentes" até aprovação)
#     - Pode propor alterações a ONGs já aprovadas — mas a alteração só entra
#       em vigor depois de o Super Administrador a validar
#     - Não pode eliminar ONGs nem aprovar/rejeitar registos ou alterações
#
#   SUPER ADMIN (Super Administrador)
#     - Pode fazer tudo o que o Admin faz, e as suas próprias alterações
#       entram em vigor de imediato (não precisam de validação)
#     - Aprova ou rejeita os registos e as alterações propostas pelo Admin
#     - Pode eliminar ONGs
#     - Vê todos os registos (incluindo pendentes e rejeitados)
#
# ─── SEGURANÇA ────────────────────────────────────────────────────────────
# As senhas NUNCA são guardadas em texto simples — apenas o seu "hash"
# (impressão digital irreversível). Isto significa que mesmo quem tiver
# acesso a este ficheiro não consegue ler as senhas reais.
#
# Em produção, defina as variáveis de ambiente abaixo em vez de editar este
# ficheiro (evita que a senha fique gravada no código-fonte/repositório):
#
#   SGIONGS_ADMIN_USER, SGIONGS_ADMIN_PASSWORD_HASH
#   SGIONGS_SUPERADMIN_USER, SGIONGS_SUPERADMIN_PASSWORD_HASH
#
# Para gerar um novo hash a partir de uma senha nova, corra:
#   python3 -c "from werkzeug.security import generate_password_hash as g; print(g('a-sua-nova-senha'))"
#
# As senhas por omissão abaixo (admin2026 / superadmin2026) são apenas para
# arrancar o sistema pela primeira vez em ambiente de testes. TROQUE-AS antes
# de disponibilizar o sistema em produção — o sistema avisa no arranque
# (ver aviso em app.py) enquanto estiverem em uso.

import os

ADMIN_USERNAME = os.environ.get('SGIONGS_ADMIN_USER', 'adminong')
ADMIN_EMAIL = (os.environ.get('SGIONGS_ADMIN_EMAIL') or '').strip().lower() or None
ADMIN_PASSWORD_HASH = os.environ.get(
    'SGIONGS_ADMIN_PASSWORD_HASH',
    # hash de 'admin2026' — apenas para arranque inicial, trocar em produção
    'scrypt:32768:8:1$1OGSxWWoKr4Quynl$e578bad968689d1d9638f7cd50a51a99684ff9fa2e1b0ccd2b6ab7af12b74602a81d0515916071b053fa691af9834734c2d70a69fb49ac3b5d0dfb6001cd368a',
)
_ADMIN_PASSWORD_E_DEFEITO = 'SGIONGS_ADMIN_PASSWORD_HASH' not in os.environ

SUPER_ADMIN_USERNAME = os.environ.get('SGIONGS_SUPERADMIN_USER', 'superadmin')
SUPER_ADMIN_EMAIL = (os.environ.get('SGIONGS_SUPERADMIN_EMAIL') or '').strip().lower() or None
SUPER_ADMIN_PASSWORD_HASH = os.environ.get(
    'SGIONGS_SUPERADMIN_PASSWORD_HASH',
    # hash de 'superadmin2026' — apenas para arranque inicial, trocar em produção
    'scrypt:32768:8:1$2DvhsqF7B72DgNGN$e2d1d6e581b6442363e69ebcd624bf1070f544b50d85a3f9a277a1b20a85a20673fb931f95108cea01ea2567a52ea47cbf2df666a77e58e7e62cdab791100efc',
)
_SUPER_ADMIN_PASSWORD_E_DEFEITO = 'SGIONGS_SUPERADMIN_PASSWORD_HASH' not in os.environ

# ─── PUBLICAÇÃO (PRODUÇÃO) ────────────────────────────────────────────────
# Em produção (SGIONGS_PRODUCAO=1) as senhas de demonstração NUNCA são aceites:
# as contas legadas só funcionam se definir o respectivo *_PASSWORD_HASH no
# ambiente. A forma recomendada é não usar contas legadas e criar o primeiro
# Super Administrador com SGIONGS_BOOTSTRAP_EMAIL + SGIONGS_BOOTSTRAP_PASSWORD
# (só é usado se ainda não existir nenhum Super Administrador na base de dados;
# a conta obriga a mudar a senha no primeiro acesso).
PRODUCAO = os.environ.get('SGIONGS_PRODUCAO', '0') == '1'
BOOTSTRAP_EMAIL = (os.environ.get('SGIONGS_BOOTSTRAP_EMAIL') or '').strip().lower() or None
BOOTSTRAP_PASSWORD = os.environ.get('SGIONGS_BOOTSTRAP_PASSWORD') or None
# Contas legadas (variáveis de ambiente) NUNCA são aceites em produção: não têm
# registo na base de dados, logo não podem ter 2FA nem rasto individual.
# Em produção usa-se SGIONGS_BOOTSTRAP_EMAIL/PASSWORD para criar o 1.º Super Administrador.
LEGADO_ADMIN_ACTIVO = not PRODUCAO
LEGADO_SUPERADMIN_ACTIVO = not PRODUCAO

# 2FA obrigatório para os perfis administrativos. Por omissão está ACTIVO em produção
# (SGIONGS_EXIGIR_2FA=0 só deve ser usado em testes). Quem ainda não o tem é levado
# a configurá-lo logo após entrar e não acede a mais nada até concluir.
PERFIS_2FA_OBRIGATORIO = ('super_admin', 'admin')
EXIGIR_2FA_ADMIN = os.environ.get('SGIONGS_EXIGIR_2FA', '1' if PRODUCAO else '0') == '1'

# Se True, alguma das duas contas ainda está a usar a senha de fábrica —
# app.py mostra um aviso persistente aos Super Administradores enquanto isto
# for verdade.
USANDO_SENHAS_POR_DEFEITO = ((_ADMIN_PASSWORD_E_DEFEITO and LEGADO_ADMIN_ACTIVO) or
                             (_SUPER_ADMIN_PASSWORD_E_DEFEITO and LEGADO_SUPERADMIN_ACTIVO))

# Tempo de sessão (minutos) até ser pedido novo login por inatividade.
DURACAO_SESSAO_MINUTOS = int(os.environ.get('SGIONGS_DURACAO_SESSAO_MINUTOS', '120'))

# (PRODUCAO, acima: '1' activa cookies "secure", HTTPS forçado e bloqueia as
# senhas de demonstração. Deixar desligado em desenvolvimento local.)
