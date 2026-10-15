# reconciliar_duplicados.py
# Junta registos duplicados: a mesma organização importada separadamente a
# partir de matrizes de províncias diferentes (ex.: "ACNUR" a aparecer como
# uma linha em CABO_DELGADO.csv e outra em NAMPULA.csv). Em vez de ficarem
# como duas ONGs distintas na base de dados, ficam como UM único registo,
# associado a todas as províncias onde realmente actua (tabela
# ong_provincias), preservando o resto da informação.
#
# Seguro para correr mais do que uma vez (idempotente): depois de juntar os
# duplicados, cada nome só tem um registo, por isso uma segunda execução não
# encontra nada para juntar.
#
# Uso: python3 reconciliar_duplicados.py [--confirmar]
#   Sem --confirmar, só mostra o que faria (modo de simulação).

import re
import sys
from database import get_connection

CAMPOS_TEXTO_A_PREENCHER = [
    'sigla', 'natureza', 'origem', 'ano_entrada_pais', 'logo_url', 'area_intervencao',
    'programas', 'projetos_em_curso', 'fonte_financiamento', 'distritos_texto',
    'perfil_grupo_alvo', 'pessoa_contacto', 'telefone', 'email', 'coordenada_x', 'coordenada_y',
]

_ACENTOS = str.maketrans('ãáâàéêíóôõúüç', 'aaaaeeiooouuc')


def normalizar_nome(nome):
    """Normalização "forte": ignora acentos, maiúsculas/minúsculas, hífens,
    barras e texto entre parênteses — para apanhar duplicados como
    "AGA KHAN" / "AGA-KHAN", "Visao Mundial" / "Visão Mundial" ou
    "APN" / "APN (Ajuda Popular da Noruega)"."""
    n = nome.strip().lower().translate(_ACENTOS)
    n = re.sub(r'\(.*?\)', ' ', n)          # remove parênteses e o que está dentro
    n = re.sub(r'[\-–_/,.]', ' ', n)        # hífens/barras/pontuação viram espaço
    n = re.sub(r'[^a-z0-9 ]', ' ', n)       # qualquer outro símbolo também
    n = re.sub(r'\s+', ' ', n).strip()
    return n


def _melhor_nome(nomes):
    """Entre várias variantes do mesmo nome, escolhe a mais completa e
    legível: mais longa (mais informação, ex. inclui a designação por
    extenso), depois não toda em maiúsculas, depois com acentuação
    portuguesa correcta (em caso de empate)."""
    def tem_acentos(n):
        return any(c in n for c in 'ãáâàéêíóôõúüçÃÁÂÀÉÊÍÓÔÕÚÜÇ')

    def pontuacao(n):
        return (len(n), 0 if n.isupper() else 1, 1 if tem_acentos(n) else 0)
    return sorted(nomes, key=pontuacao, reverse=True)[0]


def encontrar_grupos_duplicados(conn):
    linhas = conn.execute('SELECT id, nome FROM ongs ORDER BY id').fetchall()
    grupos = {}
    for l in linhas:
        chave = normalizar_nome(l['nome'])
        grupos.setdefault(chave, []).append(l['id'])
    return {chave: ids for chave, ids in grupos.items() if len(ids) > 1}


def juntar_grupo(conn, ids):
    """Junta várias linhas 'ongs' com o mesmo nome numa só (a de id mais
    baixo, por convenção — normalmente a mais antiga), preservando toda a
    informação relacionada (províncias, distritos, áreas, naturezas)."""
    ids_ordenados = sorted(ids)
    id_principal = ids_ordenados[0]
    ids_secundarios = ids_ordenados[1:]

    linhas = {r['id']: r for r in conn.execute(
        f'SELECT * FROM ongs WHERE id IN ({",".join("?" * len(ids))})', ids
    ).fetchall()}
    principal = linhas[id_principal]

    # 0. Escolher o nome mais completo/legível entre as variantes (ex.:
    #    preferir "AGA Khan Foundation" a "AGA-KHAN", ou "APN (Ajuda Popular
    #    da Noruega)" a "APN") e gravá-lo no registo principal.
    melhor_nome = _melhor_nome([linhas[i]['nome'] for i in ids_ordenados])
    if melhor_nome != principal['nome']:
        conn.execute('UPDATE ongs SET nome=? WHERE id=?', (melhor_nome, id_principal))

    # 1. Preencher no registo principal qualquer campo que esteja em branco,
    #    usando o valor da primeira linha secundária que o tiver preenchido.
    atualizacoes = {}
    for campo in CAMPOS_TEXTO_A_PREENCHER:
        if not principal[campo]:
            for id_sec in ids_secundarios:
                valor = linhas[id_sec][campo]
                if valor:
                    atualizacoes[campo] = valor
                    break
    if atualizacoes:
        sets = ', '.join(f'{c}=?' for c in atualizacoes)
        conn.execute(f'UPDATE ongs SET {sets} WHERE id=?', list(atualizacoes.values()) + [id_principal])

    # 2. Juntar todas as províncias (tanto o campo antigo 'provincia' como a
    #    tabela ong_provincias) para o registo principal.
    todas_provincias = set()
    for id_qualquer in ids_ordenados:
        if linhas[id_qualquer]['provincia']:
            todas_provincias.add(linhas[id_qualquer]['provincia'])
        for r in conn.execute('SELECT provincia FROM ong_provincias WHERE ong_id=?', (id_qualquer,)):
            todas_provincias.add(r['provincia'])
    for p in todas_provincias:
        conn.execute('INSERT OR IGNORE INTO ong_provincias (ong_id, provincia) VALUES (?, ?)', (id_principal, p))

    # 3. Juntar naturezas, distritos, áreas e ramificações das linhas
    #    secundárias para o registo principal.
    for id_sec in ids_secundarios:
        for r in conn.execute('SELECT natureza FROM ong_naturezas WHERE ong_id=?', (id_sec,)):
            conn.execute('INSERT OR IGNORE INTO ong_naturezas (ong_id, natureza) VALUES (?, ?)',
                         (id_principal, r['natureza']))
        for r in conn.execute('SELECT distrito_id FROM ong_distritos WHERE ong_id=?', (id_sec,)):
            conn.execute('INSERT OR IGNORE INTO ong_distritos (ong_id, distrito_id) VALUES (?, ?)',
                         (id_principal, r['distrito_id']))
        for r in conn.execute('SELECT area_id FROM ong_areas WHERE ong_id=?', (id_sec,)):
            conn.execute('INSERT OR IGNORE INTO ong_areas (ong_id, area_id) VALUES (?, ?)',
                         (id_principal, r['area_id']))
        for r in conn.execute('SELECT ramificacao_id FROM ong_ramificacoes WHERE ong_id=?', (id_sec,)):
            conn.execute('INSERT OR IGNORE INTO ong_ramificacoes (ong_id, ramificacao_id) VALUES (?, ?)',
                         (id_principal, r['ramificacao_id']))

    # 4. Concatenar o texto livre de distritos das linhas secundárias, para
    #    não perder informação de distritos que a deteção automática não
    #    tenha reconhecido.
    textos_distritos = {linhas[i]['distritos_texto'] for i in ids_ordenados if linhas[i]['distritos_texto']}
    if len(textos_distritos) > 1:
        conn.execute('UPDATE ongs SET distritos_texto=? WHERE id=?',
                     ('; '.join(sorted(textos_distritos)), id_principal))

    # 5. Eliminar as linhas secundárias (o ON DELETE CASCADE do schema limpa
    #    automaticamente as tabelas relacionadas que ainda lhes pertençam).
    conn.execute(f'DELETE FROM ongs WHERE id IN ({",".join("?" * len(ids_secundarios))})', ids_secundarios)

    return id_principal, ids_secundarios, sorted(todas_provincias)


def main():
    confirmar = '--confirmar' in sys.argv
    conn = get_connection()
    grupos = encontrar_grupos_duplicados(conn)

    if not grupos:
        print('Não há duplicados por juntar. A base de dados já está reconciliada.')
        conn.close()
        return

    print(f'Encontrados {len(grupos)} nomes com registos duplicados:\n')
    for chave, ids in sorted(grupos.items()):
        nome_original = conn.execute('SELECT nome FROM ongs WHERE id=?', (ids[0],)).fetchone()['nome']
        print(f'  - "{nome_original}" -> {len(ids)} registos (ids {ids})')

    if not confirmar:
        print('\nModo de simulação (nada foi alterado). Corra com --confirmar para aplicar.')
        conn.close()
        return

    conn.close()
    main_confirmado()


def main_confirmado():
    """Aplica a reconciliação sem pedir confirmação — usado quando chamado
    automaticamente a partir de importar_dados.py."""
    conn = get_connection()
    grupos = encontrar_grupos_duplicados(conn)
    if not grupos:
        print('  Nada para reconciliar.')
        conn.close()
        return
    for chave, ids in grupos.items():
        id_principal, eliminados, provincias = juntar_grupo(conn, ids)
        nome = conn.execute('SELECT nome FROM ongs WHERE id=?', (id_principal,)).fetchone()['nome']
        print(f'  OK "{nome}" -> mantido id {id_principal}, eliminados {eliminados}, províncias: {", ".join(provincias)}')
    conn.commit()
    conn.close()
    print(f'  Reconciliação concluída: {len(grupos)} grupos juntados.')


if __name__ == '__main__':
    main()
