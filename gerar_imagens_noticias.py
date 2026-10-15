"""gerar_imagens_noticias.py — Gera as 3 imagens das notícias iniciais (ilustrações originais,
desenhadas a partir dos mapas do próprio sistema). Corre-se uma vez; os JPG ficam em static/img/noticias/.
O administrador pode trocá-las em «Gerir notícias»."""
import json
import math
import os
import random

from PIL import Image, ImageDraw, ImageFilter

RAIZ = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(RAIZ, 'static', 'img', 'noticias')
W, H = 1280, 720
S = 2  # supersampling

VERDE_ESC, VERDE, VERDE_CL = (18, 62, 42), (31, 107, 70), (86, 160, 112)
OURO, AREIA, CREME = (204, 164, 78), (236, 222, 190), (247, 243, 232)


def carregar(nome):
    return json.load(open(os.path.join(RAIZ, 'static', 'data', nome), encoding='utf-8'))['features']


def aneis(geom):
    if geom['type'] == 'Polygon':
        return [geom['coordinates']]
    return geom['coordinates']


def limites(features):
    xs, ys = [], []
    for f in features:
        for poly in aneis(f['geometry']):
            for x, y in poly[0]:
                xs.append(x); ys.append(y)
    return min(xs), min(ys), max(xs), max(ys)


def projector(box, area):
    x0, y0, x1, y1 = box
    ax0, ay0, ax1, ay1 = area
    k = min((ax1 - ax0) / ((x1 - x0) * math.cos(math.radians((y0 + y1) / 2))), (ay1 - ay0) / (y1 - y0))
    w = (x1 - x0) * math.cos(math.radians((y0 + y1) / 2)) * k
    h = (y1 - y0) * k
    ox, oy = ax0 + ((ax1 - ax0) - w) / 2, ay0 + ((ay1 - ay0) - h) / 2
    c = math.cos(math.radians((y0 + y1) / 2))
    return lambda lon, lat: ((ox + (lon - x0) * c * k) * S, (oy + (y1 - lat) * k) * S)


def fundo(c1, c2):
    img = Image.new('RGB', (W * S, H * S), c1)
    d = ImageDraw.Draw(img)
    for y in range(H * S):
        t = y / (H * S)
        d.line([(0, y), (W * S, y)], fill=tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3)))
    return img


def poligonos(d, feats, proj, preencher, contorno, largura=2):
    for f in feats:
        cor = preencher(f) if callable(preencher) else preencher
        for poly in aneis(f['geometry']):
            pts = [proj(x, y) for x, y in poly[0]]
            if cor:
                d.polygon(pts, fill=cor)
            if contorno:
                d.line(pts + [pts[0]], fill=contorno, width=largura * S, joint='curve')


def pontos_luz(img, n, seed, cor=(255, 255, 255)):
    rnd = random.Random(seed)
    cam = Image.new('RGBA', img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(cam)
    for _ in range(n):
        x, y, r = rnd.randint(0, img.width), rnd.randint(0, img.height), rnd.randint(2, 7) * S
        d.ellipse([x - r, y - r, x + r, y + r], fill=cor + (rnd.randint(18, 60),))
    return Image.alpha_composite(img.convert('RGBA'), cam).convert('RGB')


def guardar(img, nome):
    img = img.resize((W, H), Image.LANCZOS)
    img.save(os.path.join(OUT, nome), 'JPEG', quality=84, optimize=True, progressive=True)
    print(nome, os.path.getsize(os.path.join(OUT, nome)) // 1024, 'KB')


def imagem_ongs():
    """País inteiro, 11 províncias em tons de verde, com rede de pontos ligados (organizações)."""
    provs = carregar('provincias_mocambique.geojson')
    img = fundo(VERDE_ESC, (12, 40, 30))
    img = pontos_luz(img, 60, 1)
    d = ImageDraw.Draw(img)
    proj = projector(limites(provs), (560, 30, 1240, 700))
    tons = [VERDE, (40, 120, 80), (26, 96, 62), (52, 132, 90), (34, 110, 72), (46, 126, 84)]
    poligonos(d, provs, proj, lambda f: tons[sum(map(ord, f['properties']['nome'])) % len(tons)], CREME, 2)
    rnd = random.Random(7)
    nos = []
    for f in provs:
        principal = max(aneis(f['geometry']), key=lambda p: len(p[0]))  # ignora ilhas pequenas
        if True:
            poly = principal
            xs = [p[0] for p in poly[0]]; ys = [p[1] for p in poly[0]]
            cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
            for _ in range(5):
                nos.append(proj(cx + rnd.uniform(-.7, .7), cy + rnd.uniform(-.9, .9)))
    for i, a in enumerate(nos):
        for b in sorted(nos[i + 1:], key=lambda p: (p[0] - a[0]) ** 2 + (p[1] - a[1]) ** 2)[:2]:
            d.line([a, b], fill=OURO, width=2 * S)
    for x, y in nos:
        d.ellipse([x - 7 * S, y - 7 * S, x + 7 * S, y + 7 * S], fill=OURO, outline=CREME, width=2 * S)
    # faixa lateral com pessoas estilizadas (círculo + corpo) — comunidade
    for i, (x, h) in enumerate([(70, 210), (170, 270), (270, 230), (370, 300), (470, 250)]):
        base = 640 * S
        cor = (CREME, AREIA, OURO, VERDE_CL, CREME)[i]
        d.ellipse([(x - 34) * S, base - h * S - 34 * S, (x + 34) * S, base - h * S + 34 * S], fill=cor)
        d.rounded_rectangle([(x - 50) * S, base - (h - 46) * S, (x + 50) * S, base], radius=40 * S, fill=cor)
    d.rectangle([0, 640 * S, 540 * S, H * S], fill=(12, 40, 30))
    return img


def imagem_mapa():
    """Distritos (159) desenhados com contorno fino; províncias a branco; escala de calor por província."""
    provs, dists = carregar('provincias_mocambique.geojson'), carregar('distritos_mocambique.geojson')
    img = fundo((226, 238, 232), (203, 224, 214))
    d = ImageDraw.Draw(img)
    proj = projector(limites(provs), (80, 24, 660, 700))
    intens = {f['properties']['nome']: v for f, v in zip(provs, [0.9, .35, .6, .2, .75, .45, 1.0, .3, .55, .25, .65])}

    def cor(f):
        t = intens.get(f['properties'].get('provincia'), .5)
        return tuple(int(a + (b - a) * t) for a, b in zip((196, 226, 206), VERDE_ESC))
    poligonos(d, dists, proj, cor, (255, 255, 255), 1)
    poligonos(d, provs, proj, None, VERDE_ESC, 3)
    # cartões de indicador (formas, sem texto) à direita
    for i, (alt, larg, cr) in enumerate([(300, 1.0, VERDE), (220, .72, OURO), (160, .5, VERDE_CL)]):
        x0, y0 = 720 * S, (60 + i * 215) * S
        d.rounded_rectangle([x0, y0, (720 + 500) * S, y0 + 180 * S], radius=18 * S, fill=CREME, outline=(210, 220, 210), width=2 * S)
        d.rounded_rectangle([x0 + 30 * S, y0 + 120 * S, x0 + (30 + 440 * larg) * S, y0 + 144 * S], radius=12 * S, fill=cr)
        d.rounded_rectangle([x0 + 30 * S, y0 + 120 * S, x0 + 470 * S, y0 + 144 * S], radius=12 * S, outline=(210, 220, 210), width=2 * S)
        d.ellipse([x0 + 30 * S, y0 + 28 * S, x0 + 78 * S, y0 + 76 * S], fill=cr)
        d.rounded_rectangle([x0 + 100 * S, y0 + 36 * S, x0 + 300 * S, y0 + 54 * S], radius=9 * S, fill=(70, 100, 85))
        d.rounded_rectangle([x0 + 100 * S, y0 + 66 * S, x0 + 220 * S, y0 + 80 * S], radius=7 * S, fill=(160, 180, 168))
    return img


def imagem_sofala():
    """Mini-mapa do país com Sofala destacada (esquerda) e zoom aos distritos de Sofala (direita), Beira em ouro."""
    provs, dists = carregar('provincias_mocambique.geojson'), carregar('distritos_mocambique.geojson')
    sof = [f for f in provs if f['properties']['nome'] == 'Sofala']
    sd = [f for f in dists if f['properties'].get('provincia') == 'Sofala']
    img = pontos_luz(fundo((20, 52, 70), (12, 34, 48)), 40, 3, (200, 230, 255))
    d = ImageDraw.Draw(img)
    mini = projector(limites(provs), (40, 40, 380, 680))
    poligonos(d, provs, mini, lambda f: (70, 140, 104) if f['properties']['nome'] == 'Sofala' else (36, 74, 92), (96, 136, 150), 1)
    zoom = projector(limites(sof), (440, 40, 1240, 690))
    poligonos(d, sd, zoom, lambda f: OURO if f['properties']['nome'] == 'Beira' else VERDE, CREME, 2)
    poligonos(d, sof, zoom, None, CREME, 4)
    for f in sd:
        if f['properties']['nome'] == 'Beira':
            pts = aneis(f['geometry'])[0][0]
            cx, cy = zoom(sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
            for r in (46, 30):
                d.ellipse([cx - r * S, cy - r * S, cx + r * S, cy + r * S], outline=OURO, width=3 * S)
            d.ellipse([cx - 12 * S, cy - 12 * S, cx + 12 * S, cy + 12 * S], fill=CREME, outline=OURO, width=4 * S)
    return img


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    guardar(imagem_ongs(), 'ongs-mocambique.jpg')
    guardar(imagem_mapa(), 'mapa-georreferenciado.jpg')
    guardar(imagem_sofala(), 'sofala-relacao.jpg')
