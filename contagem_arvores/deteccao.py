"""Deteccao e contagem de copas de arvores em imagem RGB de alta resolucao.

Metodo (classico, sem GPU e sem dados de treino):
  1. indice de vegetacao a partir do RGB (ExG / VARI / GLI) -> separa vegetacao de
     solo, telhado, agua e estrada;
  2. mapa de "copa" conforme o contraste esperado (copa escura sobre pasto claro,
     copa verde sobre solo exposto, etc.);
  3. filtro top-hat com elemento do tamanho da copa -> realca apenas objetos na
     escala de uma arvore e remove o fundo de baixa frequencia;
  4. maximos locais separados por, no minimo, 1 raio de copa -> sementes;
  5. watershed a partir das sementes -> delimitacao de cada copa;
  6. filtro por area minima/maxima de copa e recorte pelo poligono da AOI.

Imagens grandes (fazenda inteira) sao processadas em blocos com sobreposicao;
copas repetidas na emenda dos blocos sao removidas por distancia.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

# acima deste tamanho a imagem e processada em blocos
LIMITE_PIXELS_MEMORIA = 40_000_000


@dataclass
class Resultado:
    arvores: list[dict]
    area_ha: float
    resolucao_m: float
    imagem: np.ndarray
    transform: object
    crs: object
    mascara_aoi: np.ndarray
    caminho: str = ""
    escala_imagem: float = 1.0   # px da imagem em memoria por px do raster
    col_off: int = 0             # recorte usado dentro do raster (bbox da AOI)
    lin_off: int = 0
    parametros: dict = field(default_factory=dict)

    @property
    def total(self) -> int:
        return len(self.arvores)

    @property
    def densidade(self) -> float:
        return self.total / self.area_ha if self.area_ha else 0.0


def _resolucao_terreno(src) -> float:
    """Tamanho do pixel no terreno, em metros."""
    from rasterio.warp import transform as warp_transform

    res_x = abs(src.transform.a)
    crs = src.crs
    if crs is None:
        return res_x
    if crs.to_epsg() == 4326:  # graus
        lat = src.bounds.bottom + (src.bounds.top - src.bounds.bottom) / 2
        return res_x * 111_320.0 * math.cos(math.radians(lat))
    if crs.to_epsg() == 3857:  # Web Mercator: metros "esticados" pelo cosseno
        cx = src.bounds.left + (src.bounds.right - src.bounds.left) / 2
        cy = src.bounds.bottom + (src.bounds.top - src.bounds.bottom) / 2
        _, lat = warp_transform(crs, "EPSG:4326", [cx], [cy])
        return res_x * math.cos(math.radians(lat[0]))
    return res_x  # UTM, SIRGAS 2000 / UTM etc. ja em metros


def indice_vegetacao(rgb: np.ndarray, tipo: str = "exg") -> np.ndarray:
    r, g, b = (rgb[i].astype(np.float32) / 255.0 for i in range(3))
    soma = r + g + b + 1e-6
    if tipo == "vari":
        return (g - r) / (g + r - b + 1e-6)
    if tipo == "gli":
        return (2 * g - r - b) / (2 * g + r + b + 1e-6)
    return 2 * (g / soma) - (r / soma) - (b / soma)  # ExG normalizado


def _nucleo(rgb, mascara_aoi, res, raio_px, area_min, area_max, modo, indice,
            limiar_vegetacao, sensibilidade):
    """Roda a deteccao num array RGB. Devolve lista de (coluna, linha, area_m2)."""
    from scipy import ndimage as ndi
    from skimage.feature import peak_local_max
    from skimage.filters import gaussian, threshold_otsu
    from skimage.measure import regionprops
    from skimage.morphology import disk, white_tophat
    from skimage.segmentation import watershed

    if not mascara_aoi.any():
        return []
    area_px = res * res

    veg = indice_vegetacao(rgb, indice)
    veg_suave = gaussian(veg, sigma=raio_px / 3.0)
    if limiar_vegetacao is None:
        amostra = veg_suave[mascara_aoi]
        limiar_vegetacao = float(threshold_otsu(amostra)) if amostra.size > 10 else 0.0
    mascara_veg = (veg_suave >= limiar_vegetacao) & mascara_aoi
    if not mascara_veg.any():
        return []

    brilho = rgb.astype(np.float32).mean(axis=0) / 255.0
    brilho_suave = gaussian(brilho, sigma=raio_px / 3.0)

    def norm(a):
        lo, hi = np.percentile(a[mascara_aoi], [2, 98])
        return np.clip((a - lo) / (hi - lo + 1e-6), 0, 1)

    if modo == "verde":       # copa mais verde que o fundo (solo exposto, pasto seco)
        copa = norm(veg_suave)
    elif modo == "brilho":    # copa/sombra mais escura que o fundo, sem usar cor
        copa = 1.0 - norm(brilho_suave)
    else:                     # 'escuro': copa verde E mais escura que o pasto
        copa = norm(veg_suave) * (1.0 - norm(brilho_suave))

    copa = np.where(mascara_veg, copa, 0.0)
    realce = white_tophat(copa, disk(int(round(raio_px * 2))))

    valores = realce[mascara_veg]
    limiar_copa = (float(threshold_otsu(valores)) / max(sensibilidade, 1e-3)
                   if valores.size >= 10 else 1.0)
    mascara_copa = (realce >= limiar_copa) & mascara_veg

    min_px = max(4, int(area_min / area_px))
    marcados, _ = ndi.label(mascara_copa)
    if marcados.max() == 0:
        return []
    tamanhos = np.bincount(marcados.ravel())
    mascara_copa &= ~np.isin(marcados, np.flatnonzero(tamanhos < min_px))

    distancia = ndi.distance_transform_edt(mascara_copa)
    coords = peak_local_max(
        gaussian(realce, sigma=raio_px / 2.0) * mascara_copa,
        min_distance=max(2, int(round(raio_px))),
        labels=mascara_copa, exclude_border=False)
    sementes = np.zeros(mascara_copa.shape, dtype=np.int32)
    for i, (linha, coluna) in enumerate(coords, start=1):
        sementes[linha, coluna] = i

    rotulos = watershed(-distancia, markers=sementes, mask=mascara_copa)

    achados = []
    for prop in regionprops(rotulos):
        area_m2 = prop.area * area_px
        if not (area_min <= area_m2 <= area_max):
            continue
        linha, coluna = prop.centroid
        if not mascara_aoi[int(linha), int(coluna)]:
            continue
        achados.append((float(coluna), float(linha), area_m2))
    return achados


def _mascara_aoi(src, aoi, janela=None):
    from rasterio.features import geometry_mask
    from rasterio.windows import transform as janela_transform

    altura = int(janela.height) if janela is not None else src.height
    largura = int(janela.width) if janela is not None else src.width
    transform = (janela_transform(janela, src.transform) if janela is not None
                 else src.transform)
    if aoi is None or src.crs is None:
        return np.ones((altura, largura), dtype=bool), transform

    from shapely.geometry import mapping
    from rasterio.warp import transform_geom

    geom = transform_geom("EPSG:4326", src.crs, mapping(aoi))
    return geometry_mask([geom], out_shape=(altura, largura), transform=transform,
                         invert=True), transform


def detectar(
    caminho_tif,
    aoi=None,
    diametro_copa: float = 6.0,
    area_min: float | None = None,
    area_max: float | None = None,
    modo: str = "escuro",
    indice: str = "exg",
    limiar_vegetacao: float | None = None,
    sensibilidade: float = 1.2,
    bloco_px: int = 4096,
    verboso: bool = True,
) -> Resultado:
    """Conta as copas do GeoTIFF. `aoi` e um poligono shapely em WGS84 (opcional)."""
    import rasterio
    from rasterio.warp import transform as warp_transform
    from rasterio.windows import Window

    with rasterio.open(caminho_tif) as src:
        base = _janela_da_aoi(src, aoi)
        res = _resolucao_terreno(src)
        area_px = res * res
        raio_px = max(2.0, (diametro_copa / 2.0) / res)
        if area_min is None:
            area_min = math.pi * (diametro_copa * 0.30) ** 2   # copa 40% do alvo
        if area_max is None:
            area_max = math.pi * (diametro_copa * 1.50) ** 2   # copa 3x o alvo

        largura, altura = int(base.width), int(base.height)
        if largura <= 0 or altura <= 0:
            raise ValueError("O poligono nao tem sobreposicao com a imagem. "
                             "Confira se o KML e a imagem cobrem a mesma area.")
        em_blocos = largura * altura > LIMITE_PIXELS_MEMORIA
        margem = int(math.ceil(raio_px * 6))
        achados: list[tuple[float, float, float]] = []
        pixels_aoi = 0

        if em_blocos:
            passo = max(bloco_px - 2 * margem, bloco_px // 2)
            janelas = []
            for y in range(0, altura, passo):
                for x in range(0, largura, passo):
                    cx, cy = max(0, x - margem), max(0, y - margem)
                    janelas.append(Window(
                        col_off=base.col_off + cx, row_off=base.row_off + cy,
                        width=min(bloco_px, largura - cx),
                        height=min(bloco_px, altura - cy)))
            if verboso:
                print(f"  recorte da AOI: {largura}x{altura} px -> "
                      f"{len(janelas)} blocos de {bloco_px} px")
            for i, janela in enumerate(janelas, start=1):
                mascara, _ = _mascara_aoi(src, aoi, janela)
                if not mascara.any():
                    continue
                rgb = src.read(indexes=[1, 2, 3], window=janela)
                pixels_aoi += int(mascara.sum())
                locais = _nucleo(rgb, mascara, res, raio_px, area_min, area_max,
                                 modo, indice, limiar_vegetacao, sensibilidade)
                achados += [(c + janela.col_off, l + janela.row_off, a)
                            for c, l, a in locais]
                if verboso and i % 10 == 0:
                    print(f"    bloco {i}/{len(janelas)} - {len(achados)} copas",
                          flush=True)

            # copas duplicadas na sobreposicao dos blocos
            achados = _remover_duplicadas(achados, raio_px * 0.8)
            pixels_aoi = _pixels_aoi_total(src, aoi, base, bloco_px)
            fator = max(1, int(math.ceil(max(largura, altura) / 4000)))
            imagem = src.read(indexes=[1, 2, 3], window=base,
                              out_shape=(3, altura // fator, largura // fator))
            mascara_saida, _ = _mascara_aoi(src, aoi, base)
            mascara_saida = mascara_saida[::fator, ::fator]
            escala = 1.0 / fator
        else:
            mascara, _ = _mascara_aoi(src, aoi, base)
            rgb = src.read(indexes=[1, 2, 3], window=base)
            locais = _nucleo(rgb, mascara, res, raio_px, area_min, area_max,
                             modo, indice, limiar_vegetacao, sensibilidade)
            achados = [(c + base.col_off, l + base.row_off, a) for c, l, a in locais]
            pixels_aoi = int(mascara.sum())
            imagem, mascara_saida, escala = rgb, mascara, 1.0

        transform, crs = src.transform, src.crs

    arvores = []
    for coluna, linha, area_m2 in achados:
        x, y = transform * (coluna + 0.5, linha + 0.5)
        arvores.append({
            "id": len(arvores) + 1, "col": coluna, "lin": linha,
            "x": float(x), "y": float(y),
            "area_copa_m2": round(area_m2, 2),
            "diametro_copa_m": round(2 * math.sqrt(area_m2 / math.pi), 2),
        })
    if crs is not None and arvores:
        lons, lats = warp_transform(crs, "EPSG:4326",
                                    [a["x"] for a in arvores], [a["y"] for a in arvores])
        for a, lon, lat in zip(arvores, lons, lats):
            a["longitude"], a["latitude"] = round(lon, 7), round(lat, 7)

    area_ha = pixels_aoi * area_px / 10_000
    if verboso:
        print(f"  resolucao: {res:.2f} m/pixel | raio de copa: {raio_px:.1f} px")
        print(f"  area analisada: {area_ha:.2f} ha | copas validas: {len(arvores)}")

    return Resultado(
        arvores=arvores, area_ha=area_ha, resolucao_m=res, imagem=imagem,
        transform=transform, crs=crs, mascara_aoi=mascara_saida,
        caminho=str(caminho_tif), escala_imagem=escala,
        col_off=int(base.col_off), lin_off=int(base.row_off),
        parametros={
            "diametro_copa_m": diametro_copa, "modo": modo, "indice": indice,
            "area_min_m2": round(area_min, 2), "area_max_m2": round(area_max, 2),
            "limiar_vegetacao": ("automatico (Otsu)" if limiar_vegetacao is None
                                 else round(float(limiar_vegetacao), 4)),
            "sensibilidade": sensibilidade, "resolucao_m_px": round(res, 3),
            "processamento": "em blocos" if em_blocos else "imagem inteira",
        },
    )


def _remover_duplicadas(achados, distancia_min):
    """Mantem a primeira de cada par de copas mais proximas que `distancia_min`."""
    if not achados:
        return achados
    from scipy.spatial import cKDTree

    pontos = np.array([(c, l) for c, l, _ in achados])
    arvore = cKDTree(pontos)
    descartar = set()
    for i, j in arvore.query_pairs(distancia_min):
        if i not in descartar:
            descartar.add(j)
    return [a for k, a in enumerate(achados) if k not in descartar]


def _janela_da_aoi(src, aoi):
    """Recorte do raster limitado ao bounding box da AOI (evita ler a imagem toda)."""
    from rasterio.windows import Window, from_bounds

    if aoi is None or src.crs is None:
        return Window(0, 0, src.width, src.height)

    from shapely.geometry import mapping
    from rasterio.warp import transform_geom
    from shapely.geometry import shape

    limites = shape(transform_geom("EPSG:4326", src.crs, mapping(aoi))).bounds
    janela = from_bounds(*limites, transform=src.transform)
    col = max(0, int(math.floor(janela.col_off)))
    lin = max(0, int(math.floor(janela.row_off)))
    largura = min(src.width - col, int(math.ceil(janela.width)) + 1)
    altura = min(src.height - lin, int(math.ceil(janela.height)) + 1)
    return Window(col, lin, max(0, largura), max(0, altura))


def _pixels_aoi_total(src, aoi, base, bloco_px):
    """Conta os pixels dentro da AOI sem carregar a mascara inteira."""
    from rasterio.windows import Window

    if aoi is None:
        return int(base.width) * int(base.height)
    total = 0
    for y in range(0, int(base.height), bloco_px):
        for x in range(0, int(base.width), bloco_px):
            janela = Window(base.col_off + x, base.row_off + y,
                            min(bloco_px, int(base.width) - x),
                            min(bloco_px, int(base.height) - y))
            mascara, _ = _mascara_aoi(src, aoi, janela)
            total += int(mascara.sum())
    return total
