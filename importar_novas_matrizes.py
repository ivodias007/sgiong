# importar_novas_matrizes.py
# Converte as três matrizes recebidas (Niassa, Sofala, Zambézia), que têm
# layouts diferentes da "Matriz de Recolha de Informação" padrão, para os
# ficheiros .csv em data/ prontos a ser lidos pelo importar_dados.py.
#
# Uso: python importar_novas_matrizes.py

import os
import csv
import openpyxl

from tagging import normalizar, detetar_provincia, PROVINCIAS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PASTA_ORIGEM = os.path.join(BASE_DIR, 'origem_excel')
PASTA_DESTINO_CSV = os.path.join(BASE_DIR, 'data')

CAMPOS_CSV = [
    'numero_original', 'nome', 'natureza', 'origem', 'provincia', 'provincias_extra',
    'area_intervencao', 'programas', 'projetos_em_curso', 'fonte_financiamento',
    'distritos_texto', 'distritos_extra', 'perfil_grupo_alvo', 'pessoa_contacto', 'telefone', 'email',
    'coordenada_x', 'coordenada_y',
]


def limpar(v):
    if v is None:
        return ''
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    texto = str(v).strip()
    # Normalizar quebras de linha internas (células do Excel com nomes em
    # várias linhas) para não partir o CSV nem ficar feio na listagem.
    texto = ' '.join(texto.split())
    return texto


def origem_por_pais(texto_pais):
    if not texto_pais:
        return ''
    norm = normalizar(texto_pais)
    if 'mocambique' in norm or 'nacional' in norm:
        return 'Nacional'
    return 'Estrangeira'


def resolver_provincias(texto):
    """Devolve (provincia_primaria, [provincias_extra]) a partir de uma célula
    que pode conter uma província, uma lista separada por vírgulas, ou
    indicar cobertura nacional ('todo o país', 'todas as províncias')."""
    if not texto:
        return None, []
    norm = normalizar(texto)
    if 'todo o pais' in norm or 'todas' in norm and 'provincia' in norm:
        return PROVINCIAS[0], PROVINCIAS[1:]
    encontradas = []
    for parte in texto.replace(' e ', ',').split(','):
        p = detetar_provincia(parte)
        if p and p not in encontradas:
            encontradas.append(p)
    if not encontradas:
        return None, []
    return encontradas[0], encontradas[1:]


def converter_niassa():
    """Layout: N/O | G. Tematico | Nome da ONG | Pessoas de Contacto/Cargo |
    Cell | Endereço físico | Tel fixo | Fax | E-mail | Local de Actuacao | Vigência.
    'G. Tematico' só vem preenchido na primeira linha de cada grupo temático
    (fica em branco nas seguintes) -> propagamos o último valor visto."""
    caminho = os.path.join(PASTA_ORIGEM, 'BASE_DE_DADOS_ONG_NIASSA.xlsx')
    wb = openpyxl.load_workbook(caminho, data_only=True)
    ws = wb['Folha1']

    registos = []
    grupo_tematico_atual = None
    for row in ws.iter_rows(min_row=10, values_only=True):
        n_ordem, g_tematico, nome, contacto, cell, endereco, tel_fixo, fax, email, local_actuacao, vigencia = (
            list(row) + [None] * 11
        )[:11]
        if g_tematico:
            grupo_tematico_atual = limpar(g_tematico)
        nome = limpar(nome)
        if not nome:
            continue
        provincia_primaria, provincias_extra = resolver_provincias(limpar(local_actuacao)) 
        registos.append({
            'numero_original': limpar(n_ordem),
            'nome': nome,
            'natureza': '',
            'origem': '',
            'provincia': provincia_primaria or 'Niassa',
            'provincias_extra': ';'.join(provincias_extra),
            'area_intervencao': grupo_tematico_atual or '',
            'programas': '',
            'projetos_em_curso': '',
            'fonte_financiamento': '',
            'distritos_texto': limpar(local_actuacao),
            'distritos_extra': '',
            'perfil_grupo_alvo': '',
            'pessoa_contacto': limpar(contacto),
            'telefone': limpar(cell) or limpar(tel_fixo),
            'email': limpar(email),
            'coordenada_x': '',
            'coordenada_y': '',
        })
    return registos


def converter_layout_padrao_provincial(caminho, nome_folha, linha_cabecalho, primeira_linha_dados):
    """Layout partilhado por Zambézia e Sofala: Nº Ord. | Nome da ONG | País
    de Origem | Área de Intervenção | Província de Intervenção | Distrito de
    Intervenção | Fonte de Financiamento | Pessoa de contacto | Contacto | Email.
    Algumas linhas são continuações (sem nº de ordem nem nome) que só
    acrescentam mais uma área de intervenção ao registo anterior."""
    wb = openpyxl.load_workbook(caminho, data_only=True)
    ws = wb[nome_folha]

    registos = []
    registo_atual = None
    for row in ws.iter_rows(min_row=primeira_linha_dados, values_only=True):
        (n_ordem, nome, pais_origem, area, provincia_texto, distrito_texto,
         financiamento, contacto_nome, contacto_tel, email) = (list(row) + [None] * 10)[:10]

        nome = limpar(nome)
        area = limpar(area)

        if not nome and area and registo_atual:
            # linha de continuação: mais uma área de intervenção do registo anterior
            registo_atual['area_intervencao'] = (
                (registo_atual['area_intervencao'] + '; ' + area) if registo_atual['area_intervencao'] else area
            )
            continue

        if not nome:
            continue

        provincia_primaria, provincias_extra = resolver_provincias(limpar(provincia_texto))
        if not provincia_primaria:
            continue

        registo_atual = {
            'numero_original': limpar(n_ordem),
            'nome': nome,
            'natureza': '',
            'origem': origem_por_pais(limpar(pais_origem)),
            'provincia': provincia_primaria,
            'provincias_extra': ';'.join(provincias_extra),
            'area_intervencao': area,
            'programas': '',
            'projetos_em_curso': '',
            'fonte_financiamento': limpar(financiamento),
            'distritos_texto': limpar(distrito_texto),
            'distritos_extra': '',
            'perfil_grupo_alvo': '',
            'pessoa_contacto': limpar(contacto_nome),
            'telefone': limpar(contacto_tel),
            'email': limpar(email),
            'coordenada_x': '',
            'coordenada_y': '',
        }
        registos.append(registo_atual)
    return registos


def gravar_csv(provincia, registos_existentes_a_juntar, novos_registos):
    """Junta os novos registos aos que já existem no csv da província (se
    houver) e grava tudo de novo, para não perder dados de outra fonte."""
    nome_csv = normalizar(provincia).replace(' ', '_').upper() + '.csv'
    caminho = os.path.join(PASTA_DESTINO_CSV, nome_csv)
    todos = registos_existentes_a_juntar + novos_registos
    with open(caminho, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=CAMPOS_CSV)
        writer.writeheader()
        for r in todos:
            writer.writerow({k: r.get(k, '') for k in CAMPOS_CSV})
    return caminho, len(todos)


def ler_csv_existente(provincia):
    nome_csv = normalizar(provincia).replace(' ', '_').upper() + '.csv'
    caminho = os.path.join(PASTA_DESTINO_CSV, nome_csv)
    if not os.path.exists(caminho):
        return []
    with open(caminho, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def agrupar_por_provincia_primaria(registos):
    por_provincia = {}
    for r in registos:
        por_provincia.setdefault(r['provincia'], []).append(r)
    return por_provincia


def main():
    print('A converter matrizes novas (layouts não-padrão)...\n')

    todos_novos = []
    todos_novos += converter_niassa()
    print(f'  Niassa (BASE_DE_DADOS_ONG_NIASSA.xlsx): {len([r for r in todos_novos if r["provincia"] == "Niassa"])} registos lidos')

    zambezia = converter_layout_padrao_provincial(
        os.path.join(PASTA_ORIGEM, 'ONGs_que_Operam_na_Zambezia__1_.xlsx'), 'Folha1', 1, 2)
    print(f'  Zambézia (ONGs_que_Operam_na_Zambezia): {len(zambezia)} registos lidos')
    todos_novos += zambezia

    sofala = converter_layout_padrao_provincial(
        os.path.join(PASTA_ORIGEM, 'MATRIZ_ONGs_SOFALA.xlsx'), 'ONGs ', 2, 3)
    print(f'  Matriz nacional (MATRIZ_ONGs_SOFALA.xls, sheet "ONGs"): {len(sofala)} registos lidos, cobrindo várias províncias')
    todos_novos += sofala

    por_provincia = agrupar_por_provincia_primaria(todos_novos)
    print()
    for provincia, novos in por_provincia.items():
        existentes = ler_csv_existente(provincia)
        caminho, total = gravar_csv(provincia, existentes, novos)
        print(f'OK {provincia}: +{len(novos)} novos (total agora {total}) -> {os.path.relpath(caminho, BASE_DIR)}')


if __name__ == '__main__':
    main()
