"""
perfis.py — Perfis de utilizador e matriz de permissões do SGIONGs.

Introduz 6 perfis, substituindo o antigo esquema binário (admin/superadmin)
por permissões granulares. Mantém COMPATIBILIDADE com o que já existe:
as duas contas antigas (via variáveis de ambiente) continuam a funcionar
como super_admin / admin durante a transição — ver login() em app.py.
"""

PERFIS = [
    'super_admin',
    'admin',
    'gestor_nacional',
    'gestor_provincial',
    'operador',
    'consulta',
]

ROTULOS_PERFIS = {
    'super_admin': 'Super Administrador',
    'admin': 'Administrador',
    'gestor_nacional': 'Gestor Nacional',
    'gestor_provincial': 'Gestor Provincial',
    'operador': 'Operador',
    'consulta': 'Consulta',
}

DESCRICOES_PERFIS = {
    'super_admin': 'Controla tudo: dados, utilizadores, configurações e aprovações.',
    'admin': 'Gere utilizadores, dados e configurações. Não elimina registos.',
    'gestor_nacional': 'Acompanha e aprova dados de todas as províncias.',
    'gestor_provincial': 'Vê e gere apenas a sua própria província.',
    'operador': 'Cadastra e actualiza dados, mas não aprova nem elimina.',
    'consulta': 'Apenas visualiza e pesquisa — sem qualquer alteração.',
}

# Cada valor é o conjunto de ações que o perfil pode executar.
# 'ver_todas_provincias' distingue quem vê o país inteiro de quem está
# limitado à província atribuída (gestor_provincial) — ver provincia_sessao().
PERMISSOES = {
    'super_admin':       {'ver', 'criar', 'editar', 'aprovar', 'eliminar', 'gerir_utilizadores', 'gerir_noticias', 'ver_todas_provincias', 'ver_auditoria'},
    'admin':             {'ver', 'criar', 'editar', 'aprovar', 'gerir_utilizadores', 'gerir_noticias', 'ver_todas_provincias', 'ver_auditoria'},
    'gestor_nacional':   {'ver', 'criar', 'editar', 'aprovar', 'ver_todas_provincias', 'ver_auditoria'},
    'gestor_provincial': {'ver', 'criar', 'editar', 'aprovar', 'ver_auditoria'},
    'operador':          {'ver', 'criar', 'editar'},
    'consulta':          {'ver'},
}

# Só quem tem esta ação pode criar/editar contas com estes perfis-alvo —
# impede que um Administrador normal crie outro Administrador ou um Super
# Administrador (escalonamento de privilégios).
PERFIS_QUE_PODEM_ATRIBUIR = {
    'super_admin': set(PERFIS),                                    # pode atribuir qualquer perfil
    'admin': {'gestor_nacional', 'gestor_provincial', 'operador', 'consulta'},
}


def tem_permissao(perfil, accao):
    return accao in PERMISSOES.get(perfil, set())


def pode_ver_todas_provincias(perfil):
    return 'ver_todas_provincias' in PERMISSOES.get(perfil, set())


def perfis_atribuiveis_por(perfil_de_quem_cria):
    """Que perfis 'perfil_de_quem_cria' tem autorização para atribuir a outra conta."""
    return PERFIS_QUE_PODEM_ATRIBUIR.get(perfil_de_quem_cria, set())


def pode_aprovar_registo(utilizador_actual, criado_ou_solicitado_por):
    """Regra explícita: ninguém aprova o que submeteu/editou, mesmo que o seu
    perfil tenha permissão geral de aprovação."""
    if not criado_ou_solicitado_por:
        return True
    return utilizador_actual != criado_ou_solicitado_por


# Mapeamento para o esquema antigo (session['nivel']), usado pelos decoradores
# login_obrigatorio/super_admin_obrigatorio já existentes em app.py, para que
# TODAS as rotas antigas continuem a funcionar sem serem reescritas de imediato.
def nivel_legado_para_perfil(perfil):
    return 'superadmin' if perfil == 'super_admin' else 'admin'
