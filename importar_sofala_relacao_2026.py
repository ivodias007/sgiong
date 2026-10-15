#!/usr/bin/env python3
"""
importar_sofala_relacao_2026.py — Junta a "Relação Nominal de ONGs" de Sofala
(folhas Nacionais, Estrangeiras, Estrangeiras (2) e ONG Activas) ao ficheiro
data/SOFALA.csv, sem criar duplicados exactos:

  * o mesmo nome (normalizado) numa ou mais folhas = UM só registo, com os
    campos em falta preenchidos a partir das várias folhas;
  * se o nome já existe em data/SOFALA.csv, só se preenchem os campos vazios
    (nunca se sobrepõe informação já validada);
  * nomes apenas PARECIDOS não são fundidos aqui — aparecem agrupados na
    página "Possíveis Duplicados" para decisão humana.

Depois corra:  python importar_dados.py   (reconstrói a base de dados).

USO:  python importar_sofala_relacao_2026.py [caminho_do_xlsx]
"""
import csv
import os
import re
import shutil
import sys

import openpyxl

from reconciliar_duplicados import normalizar_nome

BASE = os.path.dirname(os.path.abspath(__file__))
XLSX = os.path.join(BASE, 'origem_excel', 'Relacao_Nominal_ONGs_Sofala_2026.xlsx')
CSV_SOFALA = os.path.join(BASE, 'data', 'SOFALA.csv')
CABECALHO = ['numero_original', 'nome', 'natureza', 'origem', 'provincia', 'provincias_extra',
             'area_intervencao', 'programas', 'projetos_em_curso', 'fonte_financiamento',
             'distritos_texto', 'distritos_extra', 'perfil_grupo_alvo', 'pessoa_contacto',
             'telefone', 'email', 'coordenada_x', 'coordenada_y']

# folha -> (origem por defeito, mapa campo -> nome(s) possíveis da coluna)
FOLHAS = {
    'Nacionais': 'Nacional',
    'Estrangeiras': 'Estrangeira',
    'Estrangeiras (2)': 'Estrangeira',
    'ONG Activas': 'Estrangeira',
}
ALIASES = {
    'nome': ['designacao da ong', 'nome da ong'],
    'pais': ['pais de origem'],
    'objectivos': ['objectivos da ong'],
    'financiador': ['financiador'],
    'area': ['area de intervencao', 'area tematica de actuacao', 'area de actuacao'],
    'distritos': ['local/distrito de actuacao', 'distrito que operam'],
    'representante': ['representante'],
    'telefone': ['telefone'],
    'email': ['email'],
    'ano': ['ano de implantacao', 'ano de implantacao/ren'],
}


def norm_cab(v):
    from tagging import normalizar
    return normalizar(str(v or '')).strip()


def txt(v):
    if v is None:
        return ''
    return re.sub(r'\s+', ' ', str(v)).strip()


def extrair_ano(v):
    m = re.search(r'(19|20)\d{2}', str(v or ''))
    return m.group(0) if m else ''


def ler_folha(ws, origem_def):
    # localizar linha de cabeçalho (contém "designação"/"nome da ong")
    cab_row = None
    for i, row in enumerate(ws.iter_rows(min_row=1, max_row=30, values_only=True), 1):
        n = [norm_cab(c) for c in row]
        if any(c.startswith('designacao da ong') or c.startswith('nome da ong') for c in n):
            cab_row = i
            cab = n
            break
    if not cab_row:
        return []
    col = {}
    for campo, nomes in ALIASES.items():
        for j, c in enumerate(cab):
            if c and any(c.startswith(x) for x in nomes):
                col.setdefault(campo, j)
                break
    # o TELEFONE/EMAIL ficam na linha seguinte (sub-cabeçalho)
    sub = [norm_cab(c) for c in next(ws.iter_rows(min_row=cab_row + 1, max_row=cab_row + 1, values_only=True))]
    for j, c in enumerate(sub):
        if c == 'telefone':
            col['telefone'] = j
        elif c == 'email':
            col['email'] = j
    out = []
    for row in ws.iter_rows(min_row=cab_row + 2, values_only=True):
        get = lambda k: txt(row[col[k]]) if k in col and col[k] < len(row) else ''
        nome = get('nome')
        if not nome or len(nome) < 2 or norm_cab(nome).startswith(('total', 'nota')):
            continue
        rep, tel, email = get('representante'), get('telefone'), get('email')
        # Algumas linhas da folha "ONG Activas" têm representante/e-mail trocados
        if '@' in rep and '@' not in email:
            rep, email = email, rep
        if '@' in tel:
            tel, email = '', tel
        pais = get('pais')
        origem = origem_def
        out.append({
            'nome': nome, 'origem': origem, 'area_intervencao': get('area'),
            'programas': get('objectivos'), 'fonte_financiamento': get('financiador') or '',
            'distritos_texto': '' if norm_cab(get('distritos')) in ('provincia', 'todos') else get('distritos'),
            'pessoa_contacto': rep, 'telefone': tel, 'email': email,
            'ano': extrair_ano(get('ano')), 'pais': pais,
        })
    return out


def chaves(nome):
    """Chaves de comparação: nome completo normalizado e, para nomes do tipo
    "AJULSID- Associação da ...", também a sigla antes do hífen — assim
    "FOPROSA" e "FOPROSA- Fórum Provincial..." são o mesmo registo."""
    ks = {normalizar_nome(nome)}
    m = re.match(r'^\s*([A-Za-z0-9]{2,12})\s*[-–]\s+\S', nome)
    if m:
        ks.add(normalizar_nome(m.group(1)))
    return {k for k in ks if k}


def main(xlsx=XLSX):
    wb = openpyxl.load_workbook(xlsx, data_only=True)
    novos = {}   # chave normalizada -> registo
    brutos = 0
    for nome_folha, origem in FOLHAS.items():
        if nome_folha not in wb.sheetnames:
            continue
        linhas = ler_folha(wb[nome_folha], origem)
        brutos += len(linhas)
        print(f'  {nome_folha}: {len(linhas)} linhas')
        for r in linhas:
            ks = chaves(r['nome'])
            if not ks:
                continue
            k = next((x for x in ks if x in novos), None)
            if k is None:
                k = normalizar_nome(r['nome'])
                novos[k] = r
            else:  # preenche só o que falta
                for c, v in r.items():
                    if v and not novos[k].get(c):
                        novos[k][c] = v

    existentes = []
    with open(CSV_SOFALA, encoding='utf-8-sig', newline='') as f:
        existentes = list(csv.DictReader(f))
    idx = {}
    for r in existentes:
        for kk in chaves(r['nome']):
            idx.setdefault(kk, r)
    shutil.copy(CSV_SOFALA, os.path.join(BASE, 'origem_excel', 'SOFALA_csv_antes_relacao_2026.csv'))

    adicionados = enriquecidos = 0
    for k, r in novos.items():
        k_ex = next((x for x in chaves(r['nome']) if x in idx), None)
        if k_ex:
            ex = idx[k_ex]
            mudou = False
            for campo in ('origem', 'area_intervencao', 'programas', 'fonte_financiamento', 'distritos_texto',
                          'pessoa_contacto', 'telefone', 'email'):
                if r.get(campo) and not ex.get(campo):
                    ex[campo] = r[campo]
                    mudou = True
            enriquecidos += mudou
        else:
            linha = {c: '' for c in CABECALHO}
            linha.update({c: r.get(c, '') for c in CABECALHO if c in r})
            linha['provincia'] = 'Sofala'
            existentes.append(linha)
            for kk in chaves(r['nome']):
                idx.setdefault(kk, linha)
            adicionados += 1

    with open(CSV_SOFALA, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=CABECALHO, extrasaction='ignore')
        w.writeheader()
        w.writerows(existentes)
    print(f'Linhas lidas: {brutos} | nomes únicos: {len(novos)} | novos: {adicionados} | '
          f'registos existentes enriquecidos: {enriquecidos} | total SOFALA.csv: {len(existentes)}')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else XLSX)
