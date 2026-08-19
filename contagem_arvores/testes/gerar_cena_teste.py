"""Gera uma cena sintetica de pasto com arvores (numero conhecido) para validar."""
import math, random, sys
import numpy as np, rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform as wtr

rnd = random.Random(7)
LAT, LON = -21.5, -47.5
RES_TERRENO = 0.30                      # m/pixel real
N, LADO = 1000, None
cx, cy = (v[0] for v in wtr("EPSG:4326", "EPSG:3857", [LON], [LAT]))
res_merc = RES_TERRENO / math.cos(math.radians(LAT))   # pixel em unidades 3857
x0, y0 = cx - N/2*res_merc, cy + N/2*res_merc

img = np.zeros((3, N, N), np.float32)
# pasto claro com manchas
yy, xx = np.mgrid[0:N, 0:N]
base = 0.55 + 0.08*np.sin(xx/90.0) + 0.06*np.cos(yy/70.0)
img[0] = base*0.78; img[1] = base*0.92; img[2] = base*0.50
img += np.random.default_rng(3).normal(0, 0.02, img.shape)
# estrada de terra (nao deve virar arvore)
img[:, 480:492, :] = np.array([0.62, 0.55, 0.45])[:, None, None]

verdade = []
raio_px_min = int(2.5/RES_TERRENO)
tentativas = 0
while len(verdade) < 130 and tentativas < 20000:
    tentativas += 1
    r_m = rnd.uniform(2.5, 4.0)                # raio de copa 2,5-4 m (D 5-8 m)
    r = r_m/RES_TERRENO
    px, py = rnd.uniform(r+5, N-r-5), rnd.uniform(r+5, N-r-5)
    if any(math.hypot(px-a[0], py-a[1]) < (r + a[2] + 8/RES_TERRENO) for a in verdade):
        continue
    verdade.append((px, py, r))

for px, py, r in verdade:
    d = np.hypot(xx-px, yy-py)
    # sombra deslocada (sol a NO -> sombra a SE)
    ds = np.hypot(xx-(px+r*0.7), yy-(py+r*0.9))
    som = ds <= r*0.95
    img[:, som] *= 0.55
    copa = d <= r
    tex = 0.85 + 0.15*np.sin(d*2.0)
    img[0][copa] = (0.20*tex[copa]); img[1][copa] = (0.34*tex[copa]); img[2][copa] = (0.14*tex[copa])

img = np.clip(img, 0, 1)
arr = (img*255).astype(np.uint8)
with rasterio.open("cena.tif", "w", driver="GTiff", height=N, width=N, count=3,
                   dtype="uint8", crs="EPSG:3857",
                   transform=from_origin(x0, y0, res_merc, res_merc)) as dst:
    dst.write(arr)

# KML cobrindo 90% central
m = int(N*0.05)
cantos_px = [(m, m), (N-m, m), (N-m, N-m), (m, N-m), (m, m)]
coords = []
for c, l in cantos_px:
    X, Y = x0 + c*res_merc, y0 - l*res_merc
    lo, la = (v[0] for v in wtr("EPSG:3857", "EPSG:4326", [X], [Y]))
    coords.append(f"{lo},{la},0")
open("area.kml", "w").write(
  '<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2">'
  '<Document><Placemark><name>Talhao Teste</name><Polygon><outerBoundaryIs><LinearRing>'
  f'<coordinates>{" ".join(coords)}</coordinates></LinearRing></outerBoundaryIs></Polygon>'
  '</Placemark></Document></kml>')

dentro = [t for t in verdade if m <= t[0] <= N-m and m <= t[1] <= N-m]
print(f"arvores geradas: {len(verdade)} | dentro do KML: {len(dentro)}")
open("verdade.txt","w").write(str(len(dentro)))
