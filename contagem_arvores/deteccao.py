"""Deteccao e contagem de copas de arvores em imagem RGB de alta resolucao.

Metodo (classico, sem GPU e sem dados de treino):
  1. indice de vegetacao a partir do RGB (ExG / VARI) -> separa vegetacao de solo,
     telhado, agua e estrada;
  2. mapa de "copa" conforme o contraste esperado (copa escura sobre pasto claro,
     copa verde sobre solo exposto, etc.);
  3. filtro top-hat com elemento do tamanho da copa -> realca apenas objetos na
     escala de uma arvore e remove o fundo de baixa frequencia;
  4. maximos locais separados por, no minimo, 1 raio de copa -> sementes;
  5. watershed a partir das sementes -> delimitacao de cada copa;
  6. filtro por area minima/maxima de copa e recorte pelo poligono da AOI.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


@dataclass
class Resultado:
    arvores: list[dict]
    area_ha: float
    resolucao_m: float
    rotulos: np.ndarray
    imagem: np.ndarray
    transform: object
    crs: object
    mascara_aoi: np.ndarray
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
        lon, lat = warp_transform(crs, "EPSG:4326", [cx], [cy])
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
    verboso: bool = True,
) -> Resultado:
    """Conta as copas do GeoTIFF. `aoi` e um poligono shapely em WGS84 (opcional)."""
    import rasterio
    from rasterio.features import geometry_mask
    from rasterio.warp import transform_geom
    from scipy import ndimage as ndi
    from skimage.feature import peak_local_max
    from skimage.filters import gaussian, threshold_otsu
    from skimage.morphology import disk, white_tophat
    from skimage.segmentation import watershed

    with rasterio.open(caminho_tif) as src:
        rgb = src.read(indexes=[1, 2, 3])
        transform, crs = src.transform, src.crs
        res = _resolucao_terreno(src)
        area_px = res * res

        if aoi is not None and crs is not None:
            from shapely.geometry import mapping

            geom_raster = transform_geom("EPSG:4326", crs, mapping(aoi))
            mascara_aoi = geometry_mask([geom_raster], out_shape=(src.height, src.width),
                                        transform=transform, invert=True)
        else:
            mascara_aoi = np.ones((src.shape[0], src.shape[1]), dtype=bool)

    raio_px = max(2.0, (diametro_copa / 2.0) / res)
    if area_min is None:
        area_min = math.pi * (diametro_copa * 0.30) ** 2   # copa 40% do diametro alvo
    if area_max is None:
        area_max = math.pi * (diametro_copa * 1.50) ** 2   # copa 3x o diametro alvo

    veg = indice_vegetacao(rgb, indice)
    veg_suave = gaussian(veg, sigma=raio_px / 3.0)
    if limiar_vegetacao is None:
        amostra = veg_suave[mascara_aoi]
        limiar_vegetacao = float(threshold_otsu(amostra)) if amostra.size else 0.0
    mascara_veg = (veg_suave >= limiar_vegetacao) & mascara_aoi

    brilho = rgb.astype(np.float32).mean(axis=0) / 255.0
    brilho_suave = gaussian(brilho, sigma=raio_px / 3.0)

    def norm(a):
        lo, hi = np.percentile(a[mascara_aoi], [2, 98]) if mascara_aoi.any() else (0, 1)
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
    if valores.size < 10:
        limiar_copa = 1.0
    else:
        limiar_copa = float(threshold_otsu(valores)) / max(sensibilidade, 1e-3)
    mascara_copa = (realce >= limiar_copa) & mascara_veg
    min_px = max(4, int(area_min / area_px))
    marcados, _ = ndi.label(mascara_copa)
    tamanhos = np.bincount(marcados.ravel())
    pequenos = np.isin(marcados, np.flatnonzero(tamanhos < min_px))
    mascara_copa = mascara_copa & ~pequenos

    distancia = ndi.distance_transform_edt(mascara_copa)
    coords = peak_local_max(
        gaussian(realce, sigma=raio_px / 2.0) * mascara_copa,
        min_distance=max(2, int(round(raio_px))),
        labels=mascara_copa,
        exclude_border=False,
    )
    sementes = np.zeros(mascara_copa.shape, dtype=np.int32)
    for i, (linha, coluna) in enumerate(coords, start=1):
        sementes[linha, coluna] = i

    rotulos = watershed(-distancia, markers=sementes, mask=mascara_copa)

    from skimage.measure import regionprops

    arvores = []
    for prop in regionprops(rotulos):
        area_m2 = prop.area * area_px
        if not (area_min <= area_m2 <= area_max):
            continue
        linha, coluna = prop.centroid
        if not mascara_aoi[int(linha), int(coluna)]:
            continue
        x, y = transform * (coluna + 0.5, linha + 0.5)
        arvores.append({
            "id": len(arvores) + 1,
            "col": float(coluna), "lin": float(linha),
            "x": float(x), "y": float(y),
            "area_copa_m2": round(area_m2, 2),
            "diametro_copa_m": round(2 * math.sqrt(area_m2 / math.pi), 2),
        })

    # coordenadas geograficas
    if crs is not None and arvores:
        from rasterio.warp import transform as warp_transform

        lons, lats = warp_transform(crs, "EPSG:4326",
                                    [a["x"] for a in arvores], [a["y"] for a in arvores])
        for a, lon, lat in zip(arvores, lons, lats):
            a["longitude"], a["latitude"] = round(lon, 7), round(lat, 7)

    area_ha = mascara_aoi.sum() * area_px / 10_000
    if verboso:
        print(f"  resolucao: {res:.2f} m/pixel | raio de copa: {raio_px:.1f} px")
        print(f"  area analisada: {area_ha:.2f} ha | copas validas: {len(arvores)}")

    return Resultado(
        arvores=arvores, area_ha=area_ha, resolucao_m=res, rotulos=rotulos,
        imagem=rgb, transform=transform, crs=crs, mascara_aoi=mascara_aoi,
        parametros={
            "diametro_copa_m": diametro_copa, "modo": modo, "indice": indice,
            "area_min_m2": round(area_min, 2), "area_max_m2": round(area_max, 2),
            "limiar_vegetacao": round(float(limiar_vegetacao), 4),
            "sensibilidade": sensibilidade, "resolucao_m_px": round(res, 3),
        },
    )
