#!/usr/bin/env python3
"""
gerar_mapas.py — Gera os mapas georreferenciados do SGIONGs a partir do
geoBoundaries (CC BY 4.0, https://www.geoboundaries.org):

  static/data/distritos_mocambique.geojson   (159 distritos/cidades, ADM2)
  static/data/provincias_mocambique.geojson  (11 províncias — as de ADM2 dissolvidas,
                                              por isso Maputo Cidade e Maputo Província
                                              aparecem SEPARADAS)

Os ficheiros já vêm gerados no projecto; este script só é preciso para
refazer. Fonte ADM2 completa (≈25 MB):
  https://media.githubusercontent.com/media/wmgeolab/geoBoundaries/main/releaseData/gbOpen/MOZ/ADM2/geoBoundaries-MOZ-ADM2.geojson
USO:  python gerar_mapas.py geoBoundaries-MOZ-ADM2.geojson geoBoundaries-3_0_0-MOZ-ADM1.geojson
"""
import json, re, sys, unicodedata
from shapely.geometry import shape, mapping
from shapely.ops import unary_union
from tagging import DISTRITOS_POR_PROVINCIA as D

ALIAS = {'mandlakaze': 'Mandlakazi', 'vilankulo': 'Vilanculos', 'zumbu': 'Zumbo', 'nacala': 'Nacala Porto'}
ADM1_PARA_NOSSO = {'Cabo Delgado': 'Cabo Delgado', 'Gaza': 'Gaza', 'Inhambane': 'Inhambane', 'Manica': 'Manica',
                   'Maputo': 'Maputo Província', 'Nampula': 'Nampula', 'Niassa': 'Niassa', 'Sofala': 'Sofala',
                   'Tete': 'Tete', 'Zambézia': 'Zambézia'}


def norm(s):
    s = unicodedata.normalize('NFD', s.lower())
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = re.sub(r'^cidade (da|de|do) ', '', s)
    return re.sub(r'[^a-z0-9]', '', s)


def arredondar(geom, nd=4):
    def r(c):
        return [round(c[0], nd), round(c[1], nd)]
    m = mapping(geom)
    def rec(x):
        return r(x) if isinstance(x[0], (int, float)) else [rec(i) for i in x]
    return {'type': m['type'], 'coordinates': rec(m['coordinates'])}


def main(adm2_path, adm1_path, tol=0.004):
    ours = {}
    for p, m in D.items():
        for d in m:
            ours[norm(d)] = (p, d)
    adm1 = [(f['properties']['shapeName'], shape(f['geometry'])) for f in json.load(open(adm1_path))['features']]
    feats, por_prov = [], {}
    for f in json.load(open(adm2_path))['features']:
        nome_geo = f['properties']['shapeName']
        geom = shape(f['geometry']).buffer(0)
        k = norm(nome_geo)
        tipo = 'distrito'
        if nome_geo == 'Cidade De Maputo':
            prov, nome, tipo = 'Maputo Cidade', 'Cidade de Maputo', 'cidade_maputo'
        elif nome_geo.startswith('Lago') or nome_geo.startswith('Ilha Li') or nome_geo.startswith('Ilha Ri'):
            prov, nome, tipo = None, nome_geo, 'agua'
        else:
            if k in ours:
                prov, nome = ours[k]
            elif k in ALIAS and norm(ALIAS[k]) in ours:
                prov, nome = ours[norm(ALIAS[k])]
            else:
                nome = nome_geo.replace('Cidade Da ', 'Cidade da ').replace('Cidade De ', 'Cidade de ')
                pt = geom.representative_point()
                cand = [n for n, g in adm1 if g.contains(pt)] or \
                       [min(adm1, key=lambda a: a[1].distance(pt))[0]]
                prov = ADM1_PARA_NOSSO[cand[0]]
        g2 = geom.simplify(tol, preserve_topology=True)
        if prov:
            por_prov.setdefault(prov, []).append(geom)
        feats.append({'type': 'Feature', 'properties': {'nome': nome, 'provincia': prov, 'tipo': tipo, 'chave': norm(nome)},
                      'geometry': arredondar(g2)})
    json.dump({'type': 'FeatureCollection', 'features': feats},
              open('static/data/distritos_mocambique.geojson', 'w'), ensure_ascii=False, separators=(',', ':'))
    pf = []
    for prov, geoms in sorted(por_prov.items()):
        u = unary_union([g.buffer(0.0005) for g in geoms]).buffer(-0.0005).simplify(tol, preserve_topology=True)
        pf.append({'type': 'Feature', 'properties': {'nome': prov, 'shapeName': prov, 'chave': norm(prov)},
                   'geometry': arredondar(u)})
    json.dump({'type': 'FeatureCollection', 'features': pf},
              open('static/data/provincias_mocambique.geojson', 'w'), ensure_ascii=False, separators=(',', ':'))
    print(len(feats), 'distritos;', len(pf), 'províncias:', sorted(por_prov))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
