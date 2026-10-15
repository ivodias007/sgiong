"""
importacao_web.py — Importação de matrizes Excel com pré-visualização e
validação, ANTES de gravar qualquer coisa na base de dados.

Fluxo: Excel enviado → parser genérico (converter_excel_para_csv) →
validação linha a linha → pré-visualização (contagens + tabela) →
a pessoa escolhe o que importar → só aí se grava.

Cobre o layout "padrão" (o mais comum entre as matrizes provinciais, com a
coluna "Designação da Organização" — ver converter_excel_para_csv.py). Um
ficheiro com um layout muito diferente (como os de Niassa/Sofala/Zambézia
originais) continua a precisar do pipeline por linha de comandos já
existente (importar_novas_matrizes.py) — indicado na própria página.
"""

import hashlib
import re
import uuid
from datetime import datetime, timedelta

import converter_excel_para_csv as conversor
from tagging import normalizar, PROVINCIAS, detetar_distritos
import duplicados

CAMPOS_OBRIGATORIOS = ['nome', 'provincia']  # os únicos que importar_linha() exige mesmo (ver importar_dados.py)
CAMPOS_RECOMENDADOS = ['natureza', 'origem', 'area_intervencao']  # em falta em quase metade dos dados reais já aceites — aviso, não bloqueio
VALIDADE_MINUTOS = 30

# Guardado em memória do processo — suficiente para um único servidor
# Waitress (ver render.yaml); não sobrevive a um reinício, o que é aceitável
# para uma pré-visualização de curta duração.
_PRE_VISUALIZACOES = {}


_PROV_CANONICA = {normalizar(p): p for p in PROVINCIAS}
_EMAIL_RE = re.compile(r'^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$')


def hash_ficheiro(caminho):
    h = hashlib.sha256()
    with open(caminho, 'rb') as f:
        for bloco in iter(lambda: f.read(1 << 20), b''):
            h.update(bloco)
    return h.hexdigest()


def processar_upload(caminho_xlsx):
    """Devolve (lista_de_registos, nome_ficheiro). Junta as várias
    províncias que o ficheiro possa conter numa lista só, para a
    pré-visualização mostrar tudo de uma vez."""
    registos_por_provincia, nome_ficheiro = conversor.converter_ficheiro(caminho_xlsx)
    todos = []
    for registos in registos_por_provincia.values():
        todos.extend(registos)
    return todos, nome_ficheiro


def validar_registos(conn, registos, escopo_provincia=None):
    """Marca cada registo com 'status' (valido / erro / duplicado_exato /
    duplicado_provavel) e 'motivos' (lista de strings explicando porquê)."""
    nomes_existentes = {}
    for linha in conn.execute("SELECT id, nome FROM ongs WHERE aprovacao != 'Rejeitado'"):
        nomes_existentes[normalizar(linha['nome'])] = linha['id']

    nomes_no_ficheiro = set()
    resultado = []

    for registo in registos:
        motivos = []
        status = 'valido'

        # Província tem de ser uma das 11 oficiais (normaliza maiúsculas/acentos);
        # impede criar "províncias fantasma" a partir de erros de escrita.
        prov_txt = (registo.get('provincia') or '').strip()
        if prov_txt:
            canonica = _PROV_CANONICA.get(normalizar(prov_txt))
            if canonica:
                registo = {**registo, 'provincia': canonica}
            else:
                status = 'erro'
                motivos.append(f'província "{prov_txt}" não reconhecida')

        if escopo_provincia and registo.get('provincia') != escopo_provincia:
            status = 'erro'
            motivos.append(f'fora da sua província de gestão ({escopo_provincia})')

        faltam = [c for c in CAMPOS_OBRIGATORIOS if not (registo.get(c) or '').strip()]
        if faltam:
            status = 'erro'
            motivos.append('faltam campos obrigatórios: ' + ', '.join(faltam))

        faltam_recomendados = [c for c in CAMPOS_RECOMENDADOS if not (registo.get(c) or '').strip()]
        if faltam_recomendados and status == 'valido':
            motivos.append('sem ' + ', '.join(faltam_recomendados) + ' (pode completar depois de importar)')

        # Relação territorial: se indica distritos mas nenhum pertence à província, é suspeito.
        if status != 'erro' and (registo.get('distritos_texto') or '').strip():
            if not detetar_distritos(registo['distritos_texto'], registo['provincia']):
                motivos.append('os distritos indicados não foram reconhecidos nesta província (confirme depois de importar)')
        email = (registo.get('email') or '').strip()
        if status != 'erro' and email and not all(_EMAIL_RE.match(e.strip()) for e in re.split(r'[;,/ ]+', email) if e.strip()):
            motivos.append('e-mail com formato inválido')

        nome_norm = normalizar(registo.get('nome', ''))
        if status != 'erro':
            if nome_norm in nomes_existentes:
                status = 'duplicado_exato'
                motivos.append(f'já existe na base de dados (ONG #{nomes_existentes[nome_norm]})')
            elif nome_norm in nomes_no_ficheiro:
                status = 'duplicado_exato'
                motivos.append('repetido dentro do próprio ficheiro')
            else:
                parecidos = duplicados.procurar_possiveis_duplicados(conn, registo, limite=1)
                if parecidos:
                    status = 'duplicado_provavel'
                    motivos.append(f'{parecidos[0]["pontuacao"]}% parecido com "{parecidos[0]["nome"]}" (#{parecidos[0]["id"]})')

        nomes_no_ficheiro.add(nome_norm)
        resultado.append({**registo, 'status': status, 'motivos': motivos})

    return resultado


def resumo_contagens(registos_validados):
    total = len(registos_validados)
    por_estado = {'valido': 0, 'erro': 0, 'duplicado_exato': 0, 'duplicado_provavel': 0}
    for r in registos_validados:
        por_estado[r['status']] = por_estado.get(r['status'], 0) + 1
    return {'total': total, **por_estado}


def guardar_pre_visualizacao(nome_ficheiro, registos_validados, utilizador, hash_f=None):
    _limpar_expirados()
    token = uuid.uuid4().hex
    _PRE_VISUALIZACOES[token] = {
        'criado_em': datetime.now(),
        'nome_ficheiro': nome_ficheiro,
        'registos': registos_validados,
        'utilizador': utilizador,
        'hash': hash_f,
    }
    return token


def obter_pre_visualizacao(token, utilizador=None):
    _limpar_expirados()
    entrada = _PRE_VISUALIZACOES.get(token)
    if entrada and utilizador and entrada['utilizador'] != utilizador:
        return None  # cada pré-visualização só pode ser confirmada por quem a gerou
    return entrada


def remover_pre_visualizacao(token):
    _PRE_VISUALIZACOES.pop(token, None)


def _limpar_expirados():
    limite = datetime.now() - timedelta(minutes=VALIDADE_MINUTOS)
    expirados = [t for t, v in _PRE_VISUALIZACOES.items() if v['criado_em'] < limite]
    for t in expirados:
        _PRE_VISUALIZACOES.pop(t, None)
