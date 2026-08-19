"""Download e mosaico de imagens de satelite (tiles XYZ) para a area de interesse.

IMPORTANTE (licenciamento): o Google Earth / Google Maps NAO permite raspagem
automatica de tiles. Para uso comercial use uma fonte licenciada:
  * Google Maps Static API (com chave e faturamento);
  * Mapbox Satellite (token proprio);
  * Esri World Imagery (verifique os termos do seu contrato ArcGIS);
  * imagem propria: drone, Planet, Maxar, CBERS/Amazonia-1 (INPE, gratuito).
Este modulo baixa tiles apenas do provedor que VOCE escolher e autorizar.
"""

from __future__ import annotations

import io
import math
import os
import time
from pathlib import Path

import numpy as np

TAMANHO_TILE = 256

PROVEDORES = {
    "esri": {
        "url": "https://services.arcgisonline.com/ArcGIS/rest/services/"
               "World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "zoom_max": 19,
        "credito": "Esri World Imagery (Maxar, Earthstar Geographics)",
    },
    "mapbox": {
        "url": "https://api.mapbox.com/v4/mapbox.satellite/{z}/{x}/{y}@2x.jpg90"
               "?access_token={token}",
        "zoom_max": 22,
        "credito": "Mapbox Satellite",
        "token_env": "MAPBOX_TOKEN",
        "tamanho_tile": 512,
    },
    "google": {
        "url": "https://maps.googleapis.com/maps/api/staticmap"
               "?center={lat},{lon}&zoom={z}&size=640x640&scale=2"
               "&maptype=satellite&key={token}",
        "zoom_max": 21,
        "credito": "Google Maps Static API",
        "token_env": "GOOGLE_MAPS_KEY",
        "estatico": True,
        "tamanho_tile": 1280,
    },
}


def _lonlat_para_tile(lon: float, lat: float, z: int) -> tuple[float, float]:
    n = 2.0 ** z
    x = (lon + 180.0) / 360.0 * n
    lat_rad = math.radians(lat)
    y = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    return x, y


def _tile_para_mercator(x: float, y: float, z: int) -> tuple[float, float]:
    """Canto do tile em EPSG:3857 (metros)."""
    circunferencia = 2 * math.pi * 6378137.0
    origem = -circunferencia / 2
    tamanho = circunferencia / (2 ** z)
    return origem + x * tamanho, -origem - y * tamanho


def resolucao_do_zoom(zoom: int, lat: float, tamanho_tile: int = TAMANHO_TILE) -> float:
    """Resolucao aproximada no terreno, em metros/pixel."""
    return (2 * math.pi * 6378137.0 * math.cos(math.radians(lat))
            / (tamanho_tile * 2 ** zoom))


def zoom_para_resolucao(res_alvo: float, lat: float, zoom_max: int,
                        tamanho_tile: int = TAMANHO_TILE) -> int:
    for z in range(zoom_max, 10, -1):
        if resolucao_do_zoom(z, lat, tamanho_tile) <= res_alvo:
            return z
    return zoom_max


def baixar_mosaico(geom, saida_tif: str | Path, provedor: str = "esri",
                   zoom: int | None = None, token: str | None = None,
                   url_template: str | None = None, margem_m: float = 30.0,
                   verboso: bool = True) -> Path:
    """Baixa os tiles que cobrem `geom` (WGS84) e grava um GeoTIFF EPSG:3857."""
    import rasterio
    import requests
    from PIL import Image
    from rasterio.transform import from_origin

    cfg = dict(PROVEDORES.get(provedor, {}))
    if url_template:
        cfg = {"url": url_template, "zoom_max": 22, "credito": "fonte personalizada"}
    if not cfg:
        raise ValueError(f"Provedor desconhecido: {provedor}. "
                         f"Opcoes: {', '.join(PROVEDORES)} ou --url-template")
    if cfg.get("estatico"):
        raise NotImplementedError(
            "A Google Maps Static API nao serve tiles XYZ. Baixe a imagem pela API, "
            "georreferencie no QGIS e rode com --imagem arquivo.tif")

    tamanho_tile = cfg.get("tamanho_tile", TAMANHO_TILE)
    token = token or (os.environ.get(cfg["token_env"]) if cfg.get("token_env") else None)
    if cfg.get("token_env") and not token:
        raise ValueError(f"Defina a variavel de ambiente {cfg['token_env']} "
                         f"ou use --token para o provedor {provedor}.")

    lon_min, lat_min, lon_max, lat_max = geom.bounds
    lat_centro = (lat_min + lat_max) / 2
    grau_lat = margem_m / 111_320.0
    grau_lon = margem_m / (111_320.0 * math.cos(math.radians(lat_centro)) or 1)
    lon_min, lon_max = lon_min - grau_lon, lon_max + grau_lon
    lat_min, lat_max = lat_min - grau_lat, lat_max + grau_lat

    z = zoom or cfg["zoom_max"]
    z = min(z, cfg["zoom_max"])

    x0, y0 = _lonlat_para_tile(lon_min, lat_max, z)
    x1, y1 = _lonlat_para_tile(lon_max, lat_min, z)
    tx0, ty0, tx1, ty1 = int(x0), int(y0), int(x1), int(y1)
    n_tiles = (tx1 - tx0 + 1) * (ty1 - ty0 + 1)
    if n_tiles > 4000:
        raise ValueError(f"{n_tiles} tiles no zoom {z} - area grande demais. "
                         f"Reduza o zoom ou divida a fazenda em talhoes.")

    largura = (tx1 - tx0 + 1) * tamanho_tile
    altura = (ty1 - ty0 + 1) * tamanho_tile
    mosaico = Image.new("RGB", (largura, altura))

    sessao = requests.Session()
    sessao.headers.update({"User-Agent": "vergo-contagem-arvores/1.0"})
    baixados = 0
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            url = cfg["url"].format(x=tx, y=ty, z=z, token=token or "")
            for tentativa in range(4):
                try:
                    r = sessao.get(url, timeout=30)
                    r.raise_for_status()
                    tile = Image.open(io.BytesIO(r.content)).convert("RGB")
                    mosaico.paste(tile, ((tx - tx0) * tamanho_tile,
                                         (ty - ty0) * tamanho_tile))
                    break
                except Exception as erro:
                    if tentativa == 3:
                        raise RuntimeError(f"Falha ao baixar {url}: {erro}") from erro
                    time.sleep(2 ** tentativa)
            baixados += 1
            if verboso and baixados % 25 == 0:
                print(f"  {baixados}/{n_tiles} tiles", flush=True)

    mx, my = _tile_para_mercator(tx0, ty0, z)
    resolucao = (2 * math.pi * 6378137.0) / (tamanho_tile * 2 ** z)
    transform = from_origin(mx, my, resolucao, resolucao)

    arr = np.asarray(mosaico).transpose(2, 0, 1)
    saida_tif = Path(saida_tif)
    saida_tif.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(saida_tif, "w", driver="GTiff", height=altura, width=largura,
                       count=3, dtype="uint8", crs="EPSG:3857", transform=transform,
                       compress="deflate", photometric="rgb") as dst:
        dst.write(arr)
        dst.update_tags(fonte=cfg["credito"], zoom=str(z))

    if verboso:
        res_terreno = resolucao_do_zoom(z, lat_centro, tamanho_tile)
        print(f"  mosaico: {largura}x{altura} px, zoom {z}, "
              f"~{res_terreno:.2f} m/pixel, fonte: {cfg['credito']}")
    return saida_tif
