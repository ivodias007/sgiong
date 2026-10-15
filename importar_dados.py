# importar_dados.py
# Lê os ficheiros .csv da pasta data/ (um por província, gerados pelo
# converter_excel_para_csv.py) e popula a base de dados SQLite (data/ongs.db).
#
# Este é o script que corre no Render (build command) e no arranque local.
# Não depende do openpyxl nem de nenhum ficheiro .xlsx — só de CSV puro.
#
# Uso:
#   python importar_dados.py                     -> importa todos os .csv em data/
#   python importar_dados.py caminho/ficheiro.csv -> importa um único ficheiro
#   python importar_dados.py caminho/pasta        -> importa todos os .csv dessa pasta

import sys
import os
import csv
import glob

from database import get_connection, init_db
from tagging import detetar_distritos, detetar_areas, detetar_ramificacoes, ESTRUTURA_AREAS_TEMATICAS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PASTA_DADOS_PADRAO = os.path.join(BASE_DIR, 'data')

SUB_PARA_AREA = {sub: area for area, subs in ESTRUTURA_AREAS_TEMATICAS.items() for sub in subs}


def vazio_para_none(v):
    v = (v or '').strip()
    return v if v else None


def obter_ou_criar_id(conn, tabela, nome, provincia=None):
    cur = conn.execute(f'SELECT id FROM {tabela} WHERE nome = ?', (nome,))
    linha = cur.fetchone()
    if linha:
        return linha['id']
    if provincia and tabela == 'distritos':
        cur = conn.execute('INSERT INTO distritos (nome, provincia) VALUES (?, ?)', (nome, provincia))
    else:
        cur = conn.execute(f'INSERT INTO {tabela} (nome) VALUES (?)', (nome,))
    return cur.lastrowid


def obter_ou_criar_ramificacao_id(conn, nome, area_id):
    cur = conn.execute('SELECT id FROM ramificacoes WHERE nome = ?', (nome,))
    linha = cur.fetchone()
    if linha:
        return linha['id']
    cur = conn.execute('INSERT INTO ramificacoes (nome, area_id) VALUES (?, ?)', (nome, area_id))
    return cur.lastrowid


def importar_linha(conn, linha, aprovacao=None, criado_por=None, fase_workflow=None):
    provincia = vazio_para_none(linha.get('provincia'))
    nome = vazio_para_none(linha.get('nome'))
    if not provincia or not nome:
        return None

    area_texto = vazio_para_none(linha.get('area_intervencao'))
    distritos_texto = vazio_para_none(linha.get('distritos_texto'))

    campos = ['numero_original', 'nome', 'natureza', 'origem', 'provincia',
              'area_intervencao', 'programas', 'projetos_em_curso', 'fonte_financiamento',
              'distritos_texto', 'perfil_grupo_alvo', 'pessoa_contacto', 'telefone', 'email',
              'coordenada_x', 'coordenada_y']
    valores = [
        vazio_para_none(linha.get('numero_original')), nome,
        vazio_para_none(linha.get('natureza')), vazio_para_none(linha.get('origem')), provincia,
        area_texto, vazio_para_none(linha.get('programas')), vazio_para_none(linha.get('projetos_em_curso')),
        vazio_para_none(linha.get('fonte_financiamento')), distritos_texto,
        vazio_para_none(linha.get('perfil_grupo_alvo')), vazio_para_none(linha.get('pessoa_contacto')),
        vazio_para_none(linha.get('telefone')), vazio_para_none(linha.get('email')),
        vazio_para_none(linha.get('coordenada_x')), vazio_para_none(linha.get('coordenada_y')),
    ]
    # aprovacao/criado_por/fase_workflow só são incluídos quando explicitamente
    # indicados (uso pela importação web, com pré-visualização) — as chamadas
    # existentes (pipeline por CSV) continuam a usar os valores por defeito do schema.
    if aprovacao is not None:
        campos.append('aprovacao')
        valores.append(aprovacao)
    if criado_por is not None:
        campos.append('criado_por')
        valores.append(criado_por)
    if fase_workflow is not None:
        campos.append('fase_workflow')
        valores.append(fase_workflow)

    cur = conn.execute(f'''
        INSERT INTO ongs ({", ".join(campos)}) VALUES ({", ".join(["?"] * len(campos))})
    ''', tuple(valores))
    ong_id = cur.lastrowid

    for distrito in sorted(set(detetar_distritos(distritos_texto, provincia))):
        distrito_id = obter_ou_criar_id(conn, 'distritos', distrito, provincia)
        conn.execute('INSERT OR IGNORE INTO ong_distritos (ong_id, distrito_id) VALUES (?, ?)',
                     (ong_id, distrito_id))

    distrito_extra = vazio_para_none(linha.get('distritos_extra'))
    if distrito_extra:
        distrito_id = obter_ou_criar_id(conn, 'distritos', distrito_extra, provincia)
        conn.execute('INSERT OR IGNORE INTO ong_distritos (ong_id, distrito_id) VALUES (?, ?)',
                     (ong_id, distrito_id))

    # Uma organização pode actuar em mais do que uma província (campo
    # opcional 'provincias_extra', separado por ';', usado por matrizes que
    # já vêm com várias províncias por linha).
    todas_as_provincias = [provincia]
    provincias_extra_texto = vazio_para_none(linha.get('provincias_extra'))
    if provincias_extra_texto:
        for p in provincias_extra_texto.split(';'):
            p = p.strip()
            if p and p not in todas_as_provincias:
                todas_as_provincias.append(p)
    for p in todas_as_provincias:
        conn.execute('INSERT OR IGNORE INTO ong_provincias (ong_id, provincia) VALUES (?, ?)', (ong_id, p))

    natureza_texto = vazio_para_none(linha.get('natureza'))
    if natureza_texto:
        for n in natureza_texto.split(','):
            n = n.strip()
            if n:
                conn.execute('INSERT OR IGNORE INTO ong_naturezas (ong_id, natureza) VALUES (?, ?)', (ong_id, n))

    for area in detetar_areas(area_texto):
        area_id = obter_ou_criar_id(conn, 'areas', area)
        conn.execute('INSERT OR IGNORE INTO ong_areas (ong_id, area_id) VALUES (?, ?)',
                     (ong_id, area_id))

    for ramificacao in detetar_ramificacoes(area_texto):
        area_da_ramificacao = SUB_PARA_AREA.get(ramificacao)
        if not area_da_ramificacao:
            continue
        area_id = obter_ou_criar_id(conn, 'areas', area_da_ramificacao)
        ramificacao_id = obter_ou_criar_ramificacao_id(conn, ramificacao, area_id)
        conn.execute('INSERT OR IGNORE INTO ong_ramificacoes (ong_id, ramificacao_id) VALUES (?, ?)',
                     (ong_id, ramificacao_id))

    return provincia


def importar_ficheiro(conn, caminho_csv, provincias_ja_limpas):
    nome_ficheiro = os.path.basename(caminho_csv)
    with open(caminho_csv, newline='', encoding='utf-8') as f:
        leitor = csv.DictReader(f)
        linhas = list(leitor)

    provincias_no_ficheiro = {vazio_para_none(l.get('provincia')) for l in linhas} - {None}
    for provincia in provincias_no_ficheiro:
        if provincia not in provincias_ja_limpas:
            conn.execute('DELETE FROM ongs WHERE provincia = ?', (provincia,))
            provincias_ja_limpas.add(provincia)

    resumo = {}
    for linha in linhas:
        provincia = importar_linha(conn, linha)
        if provincia:
            resumo[provincia] = resumo.get(provincia, 0) + 1
    conn.commit()

    if not resumo:
        print(f'  AVISO: nenhum registo importado de "{nome_ficheiro}" (ficheiro vazio ou sem província/nome válidos).')
        return 0

    total = 0
    for provincia, qtd in resumo.items():
        print(f'  OK {provincia}: {qtd} registos importados ({nome_ficheiro})')
        total += qtd
    return total


def listar_ficheiros(caminho):
    if os.path.isdir(caminho):
        return sorted(glob.glob(os.path.join(caminho, '*.csv')))
    if os.path.isfile(caminho):
        return [caminho]
    return []


def importar(caminho, substituir=False):
    init_db()
    # PROTECÇÃO: se a base já tem organizações (dados reais em produção),
    # não reimportar — isso substituiria os dados das províncias.
    _c = get_connection()
    _n = _c.execute('SELECT COUNT(*) FROM ongs').fetchone()[0]
    _marca = _c.execute("SELECT valor FROM configuracoes WHERE chave = 'importacao_inicial_feita'").fetchone()
    _c.close()
    if (_n > 0 or _marca) and not substituir:
        print(f'A base de dados já foi inicializada ({_n} organizações) — importação ignorada '
              f'para não perder dados. (Use --substituir só se quiser mesmo repor.)')
        return
    ficheiros = listar_ficheiros(caminho)
    if not ficheiros:
        print(f'Nenhum ficheiro .csv encontrado em: {caminho}')
        sys.exit(1)

    conn = get_connection()
    provincias_ja_limpas = set()
    total_geral = 0
    print(f'A importar {len(ficheiros)} ficheiro(s) csv...')
    for ficheiro in ficheiros:
        total_geral += importar_ficheiro(conn, ficheiro, provincias_ja_limpas)
    conn.close()
    print(f'\nImportacao concluida: {total_geral} registos no total.')

    # A mesma organização aparece por vezes em mais do que um ficheiro de
    # província (ex.: agências da ONU, que actuam em quase todo o país).
    # Reconciliamos automaticamente para não ficarem como registos duplicados.
    print('\nA reconciliar organizações duplicadas entre províncias...')
    import reconciliar_duplicados
    reconciliar_duplicados.main_confirmado()

    import noticias_iniciais
    conn = get_connection()
    conn.execute("INSERT OR REPLACE INTO configuracoes (chave, valor) VALUES ('importacao_inicial_feita', datetime('now'))")
    conn.commit()
    n = noticias_iniciais.semear(conn)
    conn.close()
    if n:
        print(f'{n} notícias iniciais criadas (editáveis em Gerir notícias).')


if __name__ == '__main__':
    _args = [a for a in sys.argv[1:] if a != '--substituir']
    _subst = '--substituir' in sys.argv
    caminho = _args[0] if _args else PASTA_DADOS_PADRAO
    if not os.path.exists(caminho):
        print(f'ERRO: Caminho nao encontrado: {caminho}')
        print('')
        print('Isto normalmente acontece por um destes dois motivos:')
        print('  1. A pasta "data/" (com os .csv das provincias) nao foi enviada')
        print('     para o GitHub. Confirma com "git status" e, se necessario:')
        print('       git add data/')
        print('       git commit -m "Adicionar dados csv"')
        print('       git push')
        print('  2. No Render, o "Root Directory" nas Settings do servico nao')
        print('     aponta para a pasta correta do repositorio.')
        sys.exit(1)
    importar(caminho, substituir=_subst)
