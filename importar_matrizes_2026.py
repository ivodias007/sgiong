#!/usr/bin/env python3
"""
importar_matrizes_2026.py — Orquestra a importação do lote de matrizes
recebido em 2026 ("Matrizes_das_ONGs.zip"), sem sobrepor manualmente os
scripts já existentes (converter_excel_para_csv.py / importar_novas_matrizes.py
/ importar_dados.py) — só os chama pela ordem certa, com os ficheiros certos.

O QUE FAZ, PASSO A PASSO
------------------------
1. Converte os 3 ficheiros .xls antigos para .xlsx (Sofala, Maputo Província,
   Zambézia) usando converter_xls_para_xlsx.py.
2. Copia todos os novos ficheiros para origem_excel/, SEM apagar os antigos
   (ficam lá como histórico; os novos têm nomes diferentes por já vir com
   nomes diferentes do lote anterior).
3. Corre converter_excel_para_csv.py sobre os ficheiros de "layout padrão"
   (os que têm a coluna "Designação da Organização") — isto já lida
   automaticamente com o caso especial de Cabo Delgado (uma folha por
   distrito), porque o parser genérico itera todas as folhas do livro.
4. Corre os parsers especiais (Niassa, Sofala, Maputo Província, Zambézia)
   que têm um layout de colunas diferente — reaproveita a lógica já testada
   em importar_novas_matrizes.py, só actualizando os nomes de ficheiro.
5. Corre importar_dados.py sobre a pasta data/ — que substitui os registos
   antigos de cada província pelos novos e RECONCILIA DUPLICADOS
   AUTOMATICAMENTE no final (chama reconciliar_duplicados.main_confirmado()).

IMPORTANTE
----------
Coloque este ficheiro na RAIZ do projecto (ao lado de app.py, tagging.py,
database.py, converter_excel_para_csv.py, importar_novas_matrizes.py,
importar_dados.py, converter_xls_para_xlsx.py) antes de correr.

Faça backup da base de dados antes de correr (o passo 5 apaga e substitui
os registos das províncias presentes nos novos ficheiros):
  cp data/ongs.db data/ongs.db.backup_antes_matrizes_2026

USO
---
  python importar_matrizes_2026.py /caminho/para/Matrizes_das_ONGs_extraido/
"""

import sys
import os
import shutil

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PASTA_ORIGEM_EXCEL = os.path.join(BASE_DIR, 'origem_excel')

# Ficheiros que já vêm no "layout padrão" (coluna "Designação da Organização"),
# processados pelo parser genérico converter_excel_para_csv.py.
FICHEIROS_LAYOUT_PADRAO = [
    'C DELGADO - Matriz.xlsx',          # 1 folha por distrito — o parser genérico já lida com isto
    'Cidade de Maputo Matriz.xlsx',
    'GAZA - Matriz.xlsx',
    'Inhambane - Matriz.xlsx',
    'MANICA - Matriz ONG.xlsx',
    'NAMPULA - Matriz ONGs.xlsx',
    'TETE - Matriz.xlsx',
]

# Ficheiros de layout especial (convertidos de .xls) — processados por
# parsers dedicados, iguais aos já usados no lote anterior.
FICHEIROS_XLS_PARA_CONVERTER = [
    'MATRIZ ONGs SOFALA.xls',
    'Provincia de Maputo Matriz.xls',
    'Zambezia- Matriz.xls',
]
FICHEIRO_NIASSA_ESPECIAL = 'NIASSA -Matiz.xlsx'


def copiar_para_origem_excel(pasta_novas_matrizes):
    os.makedirs(PASTA_ORIGEM_EXCEL, exist_ok=True)
    copiados = []
    for nome in FICHEIROS_LAYOUT_PADRAO + [FICHEIRO_NIASSA_ESPECIAL] + FICHEIROS_XLS_PARA_CONVERTER:
        origem = os.path.join(pasta_novas_matrizes, nome)
        if not os.path.exists(origem):
            print(f'  AVISO: não encontrei "{nome}" em {pasta_novas_matrizes} — a saltar.')
            continue
        destino = os.path.join(PASTA_ORIGEM_EXCEL, nome)
        shutil.copy2(origem, destino)
        copiados.append(destino)
    return copiados


def converter_xls_antigos():
    import converter_xls_para_xlsx
    convertidos = []
    for nome in FICHEIROS_XLS_PARA_CONVERTER:
        caminho = os.path.join(PASTA_ORIGEM_EXCEL, nome)
        if os.path.exists(caminho):
            novo = converter_xls_para_xlsx.converter(caminho)
            convertidos.append(os.path.basename(novo))
    return convertidos


def processar_layout_padrao():
    import converter_excel_para_csv as padrao
    for nome in FICHEIROS_LAYOUT_PADRAO:
        caminho = os.path.join(PASTA_ORIGEM_EXCEL, nome)
        if not os.path.exists(caminho):
            continue
        registos_por_provincia, nome_ficheiro = padrao.converter_ficheiro(caminho)
        for provincia, registos in registos_por_provincia.items():
            if not registos:
                print(f'  AVISO: "{nome_ficheiro}" não produziu registos para "{provincia}" '
                      f'— confirme manualmente o layout deste ficheiro.')
                continue
            caminho_csv = padrao.gravar_csv(provincia, registos)
            print(f'  OK {provincia}: {len(registos)} registos -> {os.path.relpath(caminho_csv, BASE_DIR)} '
                  f'(de {nome_ficheiro})')


def processar_layout_especial(nomes_xlsx_convertidos):
    """Niassa usa o parser dedicado já existente. Sofala/Maputo Província/
    Zambézia usam o parser 'layout padrão provincial' (colunas fixas),
    também já existente — só apontamos para os novos nomes de ficheiro."""
    import importar_novas_matrizes as especiais

    todos_novos = []

    caminho_niassa = os.path.join(PASTA_ORIGEM_EXCEL, FICHEIRO_NIASSA_ESPECIAL)
    if os.path.exists(caminho_niassa):
        especiais.PASTA_ORIGEM = PASTA_ORIGEM_EXCEL  # garantir que aponta para a pasta certa
        # A função converter_niassa() tem o nome do ficheiro fixo no código —
        # por isso chamamos a lógica directamente com o caminho novo:
        import openpyxl
        wb = openpyxl.load_workbook(caminho_niassa, data_only=True)
        ws = wb['Folha1']
        # Reutiliza o corpo da função original copiando o comportamento:
        registos = []
        grupo_tematico_atual = None
        for row in ws.iter_rows(min_row=10, values_only=True):
            n_ordem, g_tematico, nome, contacto, cell, endereco, tel_fixo, fax, email, local_actuacao, vigencia = (
                list(row) + [None] * 11
            )[:11]
            if g_tematico:
                grupo_tematico_atual = especiais.limpar(g_tematico)
            nome = especiais.limpar(nome)
            if not nome:
                continue
            provincia_primaria, provincias_extra = especiais.resolver_provincias(especiais.limpar(local_actuacao))
            registos.append({
                'numero_original': especiais.limpar(n_ordem), 'nome': nome, 'natureza': '', 'origem': '',
                'provincia': provincia_primaria or 'Niassa', 'provincias_extra': ';'.join(provincias_extra),
                'area_intervencao': grupo_tematico_atual or '', 'programas': '', 'projetos_em_curso': '',
                'fonte_financiamento': '', 'distritos_texto': especiais.limpar(local_actuacao),
                'distritos_extra': '', 'perfil_grupo_alvo': '',
                'pessoa_contacto': especiais.limpar(contacto),
                'telefone': especiais.limpar(cell) or especiais.limpar(tel_fixo),
                'email': especiais.limpar(email), 'coordenada_x': '', 'coordenada_y': '',
            })
        print(f'  Niassa ({FICHEIRO_NIASSA_ESPECIAL}): {len(registos)} registos lidos')
        todos_novos += registos

    mapa_layout_provincial = {
        'MATRIZ ONGs SOFALA.xlsx': 'ONGs ',
        'Provincia de Maputo Matriz.xlsx': 'ONGs ',
        'Zambezia- Matriz.xlsx': 'ONGs ',
    }
    for nome_xlsx, nome_folha in mapa_layout_provincial.items():
        if nome_xlsx not in nomes_xlsx_convertidos:
            continue
        caminho = os.path.join(PASTA_ORIGEM_EXCEL, nome_xlsx)
        registos = especiais.converter_layout_padrao_provincial(caminho, nome_folha, 1, 2)
        print(f'  {nome_xlsx}: {len(registos)} registos lidos (cobre possivelmente várias províncias)')
        todos_novos += registos

    por_provincia = especiais.agrupar_por_provincia_primaria(todos_novos)
    for provincia, novos in por_provincia.items():
        existentes = especiais.ler_csv_existente(provincia)
        caminho_csv, total = especiais.gravar_csv(provincia, existentes, novos)
        print(f'  OK {provincia}: +{len(novos)} novos (total agora {total}) -> {os.path.relpath(caminho_csv, BASE_DIR)}')


def main():
    if len(sys.argv) < 2:
        print('Uso: python importar_matrizes_2026.py /caminho/para/pasta/com/as/novas/matrizes')
        sys.exit(1)

    pasta_novas = sys.argv[1]
    print(f'1) A copiar ficheiros de {pasta_novas} para {PASTA_ORIGEM_EXCEL} ...')
    copiar_para_origem_excel(pasta_novas)

    print('\n2) A converter os .xls antigos (Sofala, Maputo Província, Zambézia) para .xlsx ...')
    converter_xls_antigos()
    nomes_convertidos_xlsx = [os.path.splitext(n)[0] + '.xlsx' for n in FICHEIROS_XLS_PARA_CONVERTER]

    print('\n3) A processar ficheiros de layout padrão (Cabo Delgado, Cidade de Maputo, Gaza,')
    print('   Inhambane, Manica, Nampula, Tete) ...')
    processar_layout_padrao()

    print('\n4) A processar ficheiros de layout especial (Niassa, Sofala, Maputo Província, Zambézia) ...')
    processar_layout_especial(nomes_convertidos_xlsx)

    print('\n5) A importar tudo para a base de dados (isto substitui os registos antigos')
    print('   das províncias presentes e reconcilia duplicados automaticamente) ...')
    resposta = input('   Confirma? Isto altera a base de dados. Escreva CONFIRMAR: ')
    if resposta.strip().upper() != 'CONFIRMAR':
        print('   Cancelado. Os .csv em data/ já foram actualizados, mas a base de dados NÃO foi tocada.')
        print('   Pode correr manualmente mais tarde: python importar_dados.py')
        return

    import importar_dados
    importar_dados.importar(importar_dados.PASTA_DADOS_PADRAO)

    print('\nConcluído. Reveja "Pendentes" no site para aprovar os novos registos, se aplicável.')


if __name__ == '__main__':
    main()
