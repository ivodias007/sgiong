"""
duplicados.py — Deteção de possíveis duplicados por semelhança percentual.

Complementa reconciliar_duplicados.py: aquele script junta ONGs com o MESMO
nome normalizado (uso automático durante a importação). Este módulo apanha
nomes PARECIDOS mas não idênticos (erros de digitação, abreviaturas,
pequenas variações), com uma pontuação de confiança, tal como pedido:

    "Possível duplicado — 87% de correspondência"

Nunca junta nada sozinho — só sinaliza, para uma pessoa decidir.
"""

import re
from difflib import SequenceMatcher

from tagging import normalizar

# Pesos de cada critério na pontuação final (somam 100)
PESO_NOME = 55
PESO_SIGLA = 15
PESO_TELEFONE = 15
PESO_EMAIL = 15

LIMIAR_SUGESTAO = 82  # % mínima para sugerir — calibrado para não confundir
                      # "Associação X" com "Associação Y" só pela palavra comum

# Palavras institucionais tão comuns que, sozinhas, não distinguem uma ONG
# de outra — removidas antes de calcular a semelhança do nome, para não
# gerar falsos positivos do tipo "Associação Dimongo" ~ "Associação Bassane".
PALAVRAS_GENERICAS = {
    'associacao', 'associacaos', 'fundacao', 'organizacao', 'ong', 'osc',
    'de', 'da', 'do', 'das', 'dos', 'para', 'a', 'o', 'e', 'em', 'na', 'no',
    'internacional', 'international', 'nacional', 'mocambique', 'moçambique',
}


def _nome_distintivo(nome):
    """Nome normalizado, sem as palavras institucionais genéricas — é isto
    que realmente diferencia uma ONG de outra."""
    palavras = [p for p in normalizar(nome).split() if p not in PALAVRAS_GENERICAS]
    return ' '.join(palavras) or normalizar(nome)


def _normalizar_contacto(texto):
    """Reduz telefone/email ao essencial para comparar (só dígitos para
    telefone; minúsculas e sem espaços para email)."""
    if not texto:
        return ''
    return re.sub(r'[^0-9a-z@.]', '', texto.lower())


def _semelhanca_texto(a, b):
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, _nome_distintivo(a), _nome_distintivo(b)).ratio() * 100


def calcular_semelhanca(candidata, existente):
    """Compara dois dicionários/Row com pelo menos nome/sigla/telefone/email.
    Devolve (pontuacao_0_a_100, motivos: list[str])."""
    motivos = []
    pontuacao = 0.0
    peso_usado = 0.0

    sem_nome = _semelhanca_texto(candidata.get('nome'), existente.get('nome'))
    pontuacao += sem_nome * PESO_NOME / 100
    peso_usado += PESO_NOME
    if sem_nome >= 60:
        motivos.append(f'nome {round(sem_nome)}% parecido')

    sigla_c = _normalizar_contacto(candidata.get('sigla'))
    sigla_e = _normalizar_contacto(existente.get('sigla'))
    if sigla_c and sigla_e:
        peso_usado += PESO_SIGLA
        if sigla_c == sigla_e:
            pontuacao += PESO_SIGLA
            motivos.append('mesma sigla')

    tel_c = _normalizar_contacto(candidata.get('telefone'))
    tel_e = _normalizar_contacto(existente.get('telefone'))
    if tel_c and tel_e:
        peso_usado += PESO_TELEFONE
        if tel_c == tel_e:
            pontuacao += PESO_TELEFONE
            motivos.append('mesmo telefone')

    email_c = _normalizar_contacto(candidata.get('email'))
    email_e = _normalizar_contacto(existente.get('email'))
    if email_c and email_e:
        peso_usado += PESO_EMAIL
        if email_c == email_e:
            pontuacao += PESO_EMAIL
            motivos.append('mesmo e-mail')

    # Reescala para os pesos realmente comparáveis (nem toda a ONG tem sigla/
    # telefone/email preenchidos) — evita penalizar injustamente por faltar
    # informação em vez de ela ser realmente diferente.
    if peso_usado == 0:
        return 0.0, []
    pontuacao_final = round(pontuacao / peso_usado * 100, 1)
    return pontuacao_final, motivos


def procurar_possiveis_duplicados(conn, candidata, excluir_id=None, limite=5, limiar=LIMIAR_SUGESTAO):
    """Compara 'candidata' (dict com nome/sigla/telefone/email/provincia)
    contra todas as ONGs aprovadas, devolvendo as mais parecidas acima do
    limiar. Comparação rápida o suficiente para correr ao vivo no formulário
    (poucas centenas de registos)."""
    if not candidata.get('nome'):
        return []

    query = "SELECT id, nome, sigla, telefone, email, provincia FROM ongs WHERE aprovacao = 'Aprovado'"
    params = []
    if excluir_id:
        query += ' AND id != ?'
        params.append(excluir_id)

    resultados = []
    for existente in conn.execute(query, params):
        pontuacao, motivos = calcular_semelhanca(candidata, dict(existente))
        if pontuacao >= limiar:
            resultados.append({
                'id': existente['id'], 'nome': existente['nome'], 'provincia': existente['provincia'],
                'pontuacao': pontuacao, 'motivos': motivos,
            })

    resultados.sort(key=lambda r: r['pontuacao'], reverse=True)
    return resultados[:limite]


def varrer_todos_duplicados(conn, limiar=LIMIAR_SUGESTAO):
    """Varre TODAS as ONGs aprovadas, par a par, e devolve os pares com
    semelhança acima do limiar — para a página /duplicados de revisão em
    lote. O(n²), mas n é da ordem das centenas, corre em menos de 1 segundo."""
    todas = [dict(r) for r in conn.execute(
        "SELECT id, nome, sigla, telefone, email, provincia FROM ongs WHERE aprovacao = 'Aprovado' ORDER BY id"
    )]
    ignorados = {tuple(sorted((r['ong_id_1'], r['ong_id_2'])))
                 for r in conn.execute('SELECT ong_id_1, ong_id_2 FROM duplicados_ignorados')}

    pares = []
    for i in range(len(todas)):
        for j in range(i + 1, len(todas)):
            a, b = todas[i], todas[j]
            if tuple(sorted((a['id'], b['id']))) in ignorados:
                continue
            pontuacao, motivos = calcular_semelhanca(a, b)
            if pontuacao >= limiar:
                pares.append({'a': a, 'b': b, 'pontuacao': pontuacao, 'motivos': motivos})

    pares.sort(key=lambda p: p['pontuacao'], reverse=True)
    return pares


def ignorar_par(conn, id1, id2, utilizador):
    menor, maior = sorted((id1, id2))
    conn.execute('''
        INSERT OR IGNORE INTO duplicados_ignorados (ong_id_1, ong_id_2, ignorado_por)
        VALUES (?, ?, ?)
    ''', (menor, maior, utilizador))


def agrupar_duplicados(pares):
    """Junta os pares em grupos (componentes ligados): se A~B e B~C, o
    grupo é {A, B, C} numa só linha — todos os registos com nome igual ou
    parecido aparecem juntos, não apenas aos pares."""
    pai = {}

    def achar(x):
        while pai.setdefault(x, x) != x:
            pai[x] = pai[pai[x]]
            x = pai[x]
        return x

    for p in pares:
        pai[achar(p['a']['id'])] = achar(p['b']['id'])

    membros, info = {}, {}
    for p in pares:
        raiz = achar(p['a']['id'])
        membros.setdefault(raiz, {})[p['a']['id']] = p['a']
        membros[raiz][p['b']['id']] = p['b']
        g = info.setdefault(raiz, {'pontuacao_max': 0, 'pontuacao_min': 100, 'motivos': set()})
        g['pontuacao_max'] = max(g['pontuacao_max'], p['pontuacao'])
        g['pontuacao_min'] = min(g['pontuacao_min'], p['pontuacao'])
        g['motivos'].update(p['motivos'])

    grupos = []
    for raiz, regs in membros.items():
        lista = sorted(regs.values(), key=lambda r: r['id'])
        grupos.append({
            'registos': lista,
            'ids': ','.join(str(r['id']) for r in lista),
            'pontuacao': info[raiz]['pontuacao_max'],
            'pontuacao_min': info[raiz]['pontuacao_min'],
            'motivos': sorted(info[raiz]['motivos']),
        })
    grupos.sort(key=lambda g: (-len(g['registos']), -g['pontuacao']))
    return grupos


def ignorar_grupo(conn, ids, utilizador):
    ids = sorted(set(ids))
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            ignorar_par(conn, ids[i], ids[j], utilizador)
