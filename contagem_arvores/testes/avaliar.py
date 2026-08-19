import json, math, sys, re
import rasterio
from rasterio.warp import transform as wtr

# recria a verdade de campo com a mesma semente da cena
import random
rnd = random.Random(7); N=1000; RES=0.30
verdade=[]; t=0
while len(verdade)<130 and t<20000:
    t+=1
    r_m=rnd.uniform(2.5,4.0); r=r_m/RES
    px,py=rnd.uniform(r+5,N-r-5), rnd.uniform(r+5,N-r-5)
    if any(math.hypot(px-a[0],py-a[1])<(r+a[2]+8/RES) for a in verdade): continue
    verdade.append((px,py,r))
m=int(N*0.05)
dentro=[(x,y) for x,y,_ in verdade if m<=x<=N-m and m<=y<=N-m]

det=json.load(open(sys.argv[1]))
with rasterio.open("cena.tif") as src:
    inv=~src.transform
    pontos=[]
    for f in det["features"]:
        lon,lat=f["geometry"]["coordinates"]
        X,Y=(v[0] for v in wtr("EPSG:4326",src.crs,[lon],[lat]))
        c,l=inv*(X,Y); pontos.append((c,l))

TOL=5.0/RES   # 5 m
usados=set(); tp=0
for c,l in pontos:
    melhor,dist=None,TOL
    for i,(x,y) in enumerate(dentro):
        if i in usados: continue
        d=math.hypot(c-x,l-y)
        if d<dist: dist,melhor=d,i
    if melhor is not None: usados.add(melhor); tp+=1
fp=len(pontos)-tp; fn=len(dentro)-tp
prec=tp/max(1,len(pontos)); rec=tp/max(1,len(dentro))
print(f"verdade={len(dentro)} detectadas={len(pontos)} TP={tp} FP={fp} FN={fn}")
print(f"precisao={prec:.1%} recall={rec:.1%} F1={2*prec*rec/max(1e-9,prec+rec):.1%} "
      f"erro_na_contagem={(len(pontos)-len(dentro))/len(dentro):+.1%}")
