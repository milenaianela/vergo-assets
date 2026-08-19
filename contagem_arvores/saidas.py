"""Saidas: KML para o Google Earth, GeoJSON, CSV, imagem de conferencia e amostras."""

from __future__ import annotations

import csv
import json
import random
from pathlib import Path
from xml.sax.saxutils import escape


def escrever_kml(resultado, caminho, nome="Arvores detectadas"):
    caminho = Path(caminho)
    partes = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
        f"<name>{escape(nome)}</name>",
        '<Style id="arvore"><IconStyle><scale>0.6</scale><color>ff00c814</color>'
        '<Icon><href>http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png</href>'
        "</Icon></IconStyle><LabelStyle><scale>0</scale></LabelStyle></Style>",
        f"<Folder><name>{len(resultado.arvores)} arvores</name>",
    ]
    for a in resultado.arvores:
        if "longitude" not in a:
            continue
        partes.append(
            f"<Placemark><name>{a['id']}</name><styleUrl>#arvore</styleUrl>"
            f"<description>copa: {a['diametro_copa_m']} m | "
            f"area: {a['area_copa_m2']} m2</description>"
            f"<Point><coordinates>{a['longitude']},{a['latitude']},0</coordinates></Point>"
            "</Placemark>"
        )
    partes += ["</Folder></Document></kml>"]
    caminho.write_text("\n".join(partes), encoding="utf-8")
    return caminho


def escrever_geojson(resultado, caminho):
    feicoes = [
        {
            "type": "Feature",
            "geometry": {"type": "Point",
                         "coordinates": [a.get("longitude"), a.get("latitude")]},
            "properties": {k: v for k, v in a.items()
                           if k not in ("x", "y", "col", "lin")},
        }
        for a in resultado.arvores if "longitude" in a
    ]
    Path(caminho).write_text(
        json.dumps({"type": "FeatureCollection", "features": feicoes}, ensure_ascii=False),
        encoding="utf-8")
    return Path(caminho)


def escrever_csv(resultado, caminho):
    campos = ["id", "longitude", "latitude", "area_copa_m2", "diametro_copa_m"]
    with Path(caminho).open("w", newline="", encoding="utf-8") as f:
        escritor = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        escritor.writeheader()
        escritor.writerows(resultado.arvores)
    return Path(caminho)


def salvar_conferencia(resultado, caminho, aoi_pixels=None, max_lado=2500):
    """PNG com a imagem original e um circulo sobre cada copa detectada."""
    import numpy as np
    from PIL import Image, ImageDraw

    img = Image.fromarray(resultado.imagem.transpose(1, 2, 0).astype("uint8"))
    escala = min(1.0, max_lado / max(img.size))
    desenho_img = img.resize((int(img.width * escala), int(img.height * escala))) \
        if escala < 1 else img.copy()
    desenho = ImageDraw.Draw(desenho_img)
    raio = max(3, int(3 * escala * 2))
    for a in resultado.arvores:
        cx, cy = a["col"] * escala, a["lin"] * escala
        r = max(3.0, (a["diametro_copa_m"] / 2 / resultado.resolucao_m) * escala)
        desenho.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 40, 40), width=2)
    desenho_img.save(caminho)
    return Path(caminho)


def salvar_amostras(resultado, pasta, n=8, lado_m=100, semente=42):
    """Recorta parcelas quadradas para conferencia manual (validacao da contagem)."""
    from PIL import Image, ImageDraw

    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    img = Image.fromarray(resultado.imagem.transpose(1, 2, 0).astype("uint8"))
    lado_px = int(lado_m / resultado.resolucao_m)
    rnd = random.Random(semente)
    altura, largura = resultado.mascara_aoi.shape
    linhas = []
    tentativas = 0
    while len(linhas) < n and tentativas < n * 200:
        tentativas += 1
        if largura <= lado_px or altura <= lado_px:
            break
        x0 = rnd.randint(0, largura - lado_px)
        y0 = rnd.randint(0, altura - lado_px)
        recorte_mascara = resultado.mascara_aoi[y0:y0 + lado_px, x0:x0 + lado_px]
        if recorte_mascara.mean() < 0.98:      # so parcelas 100% dentro da AOI
            continue
        dentro = [a for a in resultado.arvores
                  if x0 <= a["col"] < x0 + lado_px and y0 <= a["lin"] < y0 + lado_px]
        recorte = img.crop((x0, y0, x0 + lado_px, y0 + lado_px)).resize((900, 900))
        marcado = recorte.copy()
        desenho = ImageDraw.Draw(marcado)
        fator = 900 / lado_px
        for a in dentro:
            cx, cy = (a["col"] - x0) * fator, (a["lin"] - y0) * fator
            r = max(4.0, (a["diametro_copa_m"] / 2 / resultado.resolucao_m) * fator)
            desenho.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 40, 40), width=3)
        idx = len(linhas) + 1
        recorte.save(pasta / f"parcela_{idx:02d}_limpa.png")
        marcado.save(pasta / f"parcela_{idx:02d}_detectado.png")
        linhas.append({"parcela": idx, "lado_m": lado_m,
                       "area_ha": round(lado_m * lado_m / 10_000, 4),
                       "contagem_automatica": len(dentro), "contagem_manual": ""})

    with (pasta / "validacao.csv").open("w", newline="", encoding="utf-8") as f:
        escritor = csv.DictWriter(f, fieldnames=["parcela", "lado_m", "area_ha",
                                                 "contagem_automatica", "contagem_manual"])
        escritor.writeheader()
        escritor.writerows(linhas)
    return pasta, linhas


def escrever_relatorio(resultado, caminho, nome_area="", fonte_imagem="", nomes=()):
    linhas = [
        "RELATORIO DE CONTAGEM DE ARVORES POR IMAGEM DE SATELITE",
        "=" * 58,
        f"Area: {nome_area or '-'}",
        f"Talhoes no arquivo: {', '.join(nomes) if nomes else '-'}",
        f"Fonte da imagem: {fonte_imagem or '-'}",
        "",
        f"Area analisada.............: {resultado.area_ha:.2f} ha",
        f"Arvores detectadas.........: {resultado.total}",
        f"Densidade..................: {resultado.densidade:.1f} arvores/ha",
        f"Resolucao da imagem........: {resultado.resolucao_m:.2f} m/pixel",
        "",
        "Parametros usados:",
    ]
    linhas += [f"  - {k}: {v}" for k, v in resultado.parametros.items()]
    if resultado.arvores:
        import statistics

        diam = [a["diametro_copa_m"] for a in resultado.arvores]
        linhas += [
            "",
            "Copas detectadas:",
            f"  - diametro medio...: {statistics.mean(diam):.2f} m",
            f"  - mediana..........: {statistics.median(diam):.2f} m",
            f"  - minimo / maximo..: {min(diam):.2f} m / {max(diam):.2f} m",
        ]
    linhas += [
        "",
        "OBSERVACAO TECNICA",
        "A contagem automatica em imagem RGB de satelite e uma ESTIMATIVA. Copas",
        "encostadas sao contadas como uma unica arvore e individuos suprimidos sob",
        "dossel fechado nao aparecem. Valide com as parcelas amostrais geradas",
        "(pasta 'amostras') antes de usar o numero em laudo, inventario ou processo",
        "de autorizacao de supressao.",
    ]
    Path(caminho).write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return Path(caminho)
