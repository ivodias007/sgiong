#!/usr/bin/env python3
"""
baixar_mapa_provincias.py — Descarrega as fronteiras reais das províncias
de Moçambique a partir do geoBoundaries (dados abertos, licença CC BY 4.0).

Fonte: https://www.geoboundaries.org  (William & Mary geoLab)
Atribuição obrigatória pela licença — mantenha o comentário de fonte no
rodapé do mapa (já incluído no template indicadores.html).

USO:
  pip install requests --break-system-packages
  python baixar_mapa_provincias.py

RESULTADO:
  static/data/provincias_mocambique.geojson
"""

import json
import os
import urllib.request

API_URL = "https://www.geoboundaries.org/api/current/gbOpen/MOZ/ADM1/"
DESTINO = "static/data/provincias_mocambique.geojson"


def main():
    print(f"🔎 A consultar metadados em {API_URL} ...")
    with urllib.request.urlopen(API_URL) as resp:
        metadados = json.loads(resp.read().decode())

    # A API devolve uma lista com um único item para um país+nível específico
    item = metadados[0] if isinstance(metadados, list) else metadados
    url_geojson = item["gjDownloadURL"]
    print(f"⬇️  A descarregar GeoJSON de: {url_geojson}")

    os.makedirs(os.path.dirname(DESTINO), exist_ok=True)
    urllib.request.urlretrieve(url_geojson, DESTINO)

    print(f"✅ Guardado em: {DESTINO}")
    print("   Fonte: geoBoundaries.org (CC BY 4.0) — mantenha a atribuição no site.")


if __name__ == "__main__":
    main()
