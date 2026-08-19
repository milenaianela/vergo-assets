"""Leitura da area de interesse (AOI): KML, KMZ ou GeoJSON -> poligono em WGS84."""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from shapely.geometry import MultiPolygon, Polygon, shape
from shapely.ops import unary_union


def _parse_xml(dados: bytes):
    """Parse tolerante: KML do Google Earth costuma usar prefixos nao declarados."""
    try:
        return ET.fromstring(dados)
    except ET.ParseError:
        pass
    texto = dados.decode("utf-8", errors="replace")
    usados = set(re.findall(r"[<\s]([A-Za-z_][\w.-]*):[A-Za-z_]", texto))
    declarados = set(re.findall(r'xmlns:([\w.-]+)\s*=', texto)) | {"xml", "xmlns"}
    faltando = usados - declarados
    if faltando:
        raiz_match = re.search(r"<([A-Za-z_][\w.-]*)([^>]*?)(/?)>", texto)
        if raiz_match:
            extra = "".join(f' xmlns:{p}="urn:prefixo-nao-declarado:{p}"' for p in faltando)
            inicio, fim = raiz_match.span()
            abertura = texto[inicio:fim]
            texto = texto[:inicio] + abertura[:-1] + extra + abertura[-1] + texto[fim:]
    return ET.fromstring(texto.encode("utf-8"))


def _tag(elem) -> str:
    """Nome do elemento sem o namespace (KML do Google Earth varia bastante)."""
    return elem.tag.split("}")[-1]


def _parse_coords(texto: str) -> list[tuple[float, float]]:
    pontos = []
    for bruto in texto.replace("\n", " ").replace("\t", " ").split():
        partes = bruto.split(",")
        if len(partes) >= 2:
            try:
                pontos.append((float(partes[0]), float(partes[1])))
            except ValueError:
                continue
    return pontos


def _poligonos_kml(raiz) -> list[Polygon]:
    poligonos = []
    for elem in raiz.iter():
        if _tag(elem) != "Polygon":
            continue
        externo, buracos = None, []
        for filho in elem.iter():
            nome = _tag(filho)
            if nome not in ("outerBoundaryIs", "innerBoundaryIs"):
                continue
            coords_elem = [c for c in filho.iter() if _tag(c) == "coordinates"]
            if not coords_elem or not coords_elem[0].text:
                continue
            anel = _parse_coords(coords_elem[0].text)
            if len(anel) < 4:
                continue
            if nome == "outerBoundaryIs":
                externo = anel
            else:
                buracos.append(anel)
        if externo:
            poligonos.append(Polygon(externo, buracos))

    # Fallback: KML com LinearRing/LineString solto, sem <Polygon>.
    if not poligonos:
        for elem in raiz.iter():
            if _tag(elem) not in ("LinearRing", "LineString"):
                continue
            coords_elem = [c for c in elem.iter() if _tag(c) == "coordinates"]
            if coords_elem and coords_elem[0].text:
                anel = _parse_coords(coords_elem[0].text)
                if len(anel) >= 4:
                    poligonos.append(Polygon(anel))
    return poligonos


def _nome(elem) -> str | None:
    for filho in elem:
        if _tag(filho) == "name":
            return (filho.text or "").strip() or None
    return None


def _atributos(pm) -> dict:
    """SimpleData/Data do Placemark (ex.: Fazenda, Talhao, Area_ha)."""
    dados = {}
    for elem in pm.iter():
        t = _tag(elem)
        if t == "SimpleData" and elem.get("name"):
            dados[elem.get("name")] = (elem.text or "").strip()
        elif t == "Data" and elem.get("name"):
            valor = next((v.text for v in elem if _tag(v) == "value"), None)
            if valor:
                dados[elem.get("name")] = valor.strip()
    if not dados:  # Google Earth Pro guarda os atributos numa tabela HTML
        desc = next((d.text for d in pm.iter()
                     if _tag(d) == "description" and d.text), None)
        if desc:
            for linha in re.findall(r"<tr[^>]*>(.*?)</tr>", desc, re.S | re.I):
                celulas = [re.sub(r"<[^>]+>", "", c).strip()
                           for c in re.findall(r"<td[^>]*>(.*?)</td>", linha, re.S | re.I)]
                if len(celulas) >= 2 and celulas[0] and celulas[0] not in dados:
                    dados[celulas[0]] = celulas[1]
    return dados


def _raiz(caminho: Path):
    sufixo = caminho.suffix.lower()
    if sufixo == ".kmz":
        with zipfile.ZipFile(caminho) as z:
            internos = [n for n in z.namelist() if n.lower().endswith(".kml")]
            if not internos:
                raise ValueError(f"{caminho.name}: KMZ sem nenhum .kml dentro.")
            return _parse_xml(z.read(internos[0]))
    return _parse_xml(caminho.read_bytes())


def listar_camadas(caminho: str | Path) -> list[dict]:
    """Pastas (Folder/Document) do KML, com contagem e area de cada uma."""
    raiz = _raiz(Path(caminho))
    camadas = []

    def caminhar(elem, nivel=0):
        for filho in elem:
            if _tag(filho) not in ("Folder", "Document"):
                continue
            pms = [p for p in filho.iter() if _tag(p) == "Placemark"]
            poligonos = [q.buffer(0) for p in pms for q in _poligonos_kml(p)]
            geom = unary_union(poligonos) if poligonos else None
            camadas.append({
                "nome": _nome(filho) or "(sem nome)", "nivel": nivel,
                "placemarks": len(pms), "poligonos": len(poligonos),
                "area_ha": area_hectares(geom) if geom is not None else 0.0,
                "geom": geom,
            })
            caminhar(filho, nivel + 1)

    caminhar(raiz)
    return camadas


def carregar_placemarks(caminho: str | Path, camada: str | None = None) -> list[dict]:
    """Um registro por Placemark: nome, geometria WGS84, area e atributos."""
    raiz = _raiz(Path(caminho))
    escopo = [raiz]
    if camada:
        escopo = [e for e in raiz.iter() if _tag(e) in ("Folder", "Document")
                  and (_nome(e) or "").lower() == camada.lower()]
        if not escopo:
            disponiveis = [c["nome"] for c in listar_camadas(caminho)]
            raise ValueError(f"Camada '{camada}' nao encontrada. "
                             f"Disponiveis: {disponiveis}")

    # nome da pasta mais interna que contem cada Placemark
    dono = {}
    for pasta in raiz.iter():
        if _tag(pasta) in ("Folder", "Document"):
            nome_pasta = _nome(pasta)
            for pm in pasta.iter():
                if _tag(pm) == "Placemark" and nome_pasta:
                    dono[id(pm)] = nome_pasta

    registros = []
    for raiz_escopo in escopo:
        for pm in raiz_escopo.iter():
            if _tag(pm) != "Placemark":
                continue
            poligonos = [p.buffer(0) for p in _poligonos_kml(pm)]
            poligonos = [p for p in poligonos if not p.is_empty]
            if not poligonos:
                continue
            geom = unary_union(poligonos)
            registros.append({
                "nome": _nome(pm), "camada": dono.get(id(pm), ""), "geom": geom,
                "n_poligonos": len(poligonos), "area_ha": area_hectares(geom),
                "atributos": _atributos(pm),
            })
    return registros


def carregar_aoi(caminho: str | Path, camada: str | None = None):
    """Devolve (geometria WGS84, lista de nomes dos talhoes)."""
    if camada:
        registros = carregar_placemarks(caminho, camada)
        if not registros:
            raise ValueError(f"Camada '{camada}' nao tem nenhum poligono.")
        return (unary_union([r["geom"] for r in registros]),
                [r["nome"] for r in registros if r["nome"]])

    caminho = Path(caminho)
    sufixo = caminho.suffix.lower()

    if sufixo in (".kml", ".kmz"):
        raiz = _raiz(caminho)
        poligonos = _poligonos_kml(raiz)
        nomes = [e.text for e in raiz.iter() if _tag(e) == "name" and e.text]
    elif sufixo in (".geojson", ".json"):
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        feicoes = dados.get("features", [dados])
        poligonos, nomes = [], []
        for f in feicoes:
            geom = shape(f.get("geometry", f))
            if isinstance(geom, Polygon):
                poligonos.append(geom)
            elif isinstance(geom, MultiPolygon):
                poligonos.extend(geom.geoms)
            nome = (f.get("properties") or {}).get("name")
            if nome:
                nomes.append(nome)
    else:
        raise ValueError(f"Formato nao suportado: {sufixo}. Use .kml, .kmz ou .geojson")

    poligonos = [p.buffer(0) for p in poligonos if p.is_valid or p.buffer(0).is_valid]
    poligonos = [p for p in poligonos if not p.is_empty and p.area > 0]
    if not poligonos:
        raise ValueError(f"{caminho.name}: nenhum poligono encontrado no arquivo.")

    geom = unary_union(poligonos)
    return geom, nomes


def area_hectares(geom) -> float:
    """Area do poligono WGS84 em hectares (projecao equivalente local)."""
    import math

    lat0 = geom.centroid.y
    m_por_grau_lat = 111_132.92 - 559.82 * math.cos(2 * math.radians(lat0))
    m_por_grau_lon = 111_412.84 * math.cos(math.radians(lat0))
    from shapely.affinity import scale

    return scale(geom, xfact=m_por_grau_lon, yfact=m_por_grau_lat, origin=(0, 0, 0)).area / 10_000
