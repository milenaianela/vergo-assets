#!/usr/bin/env python3
"""Conta arvores dentro do poligono de um KML usando imagem de satelite RGB.

Exemplos:
  # 1) usando imagem propria ja georreferenciada (drone, Planet, export do QGIS)
  python -m contagem_arvores.contar_arvores fazenda.kml --imagem orto.tif

  # 2) baixando o mosaico do provedor que voce tem licenca para usar
  python -m contagem_arvores.contar_arvores fazenda.kml --baixar --provedor esri

  # ajuste fino do tamanho medio de copa e da sensibilidade
  python -m contagem_arvores.contar_arvores fazenda.kml --imagem orto.tif \
      --diametro-copa 4 --sensibilidade 1.3 --modo escuro
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Contagem de arvores por imagem de satelite a partir de um KML.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("kml", help="arquivo .kml, .kmz ou .geojson com o perimetro da area")
    p.add_argument("--imagem", help="GeoTIFF RGB ja georreferenciado da area")
    p.add_argument("--baixar", action="store_true",
                   help="baixar mosaico de tiles do provedor escolhido")
    p.add_argument("--provedor", default="esri", help="esri | mapbox (padrao: esri)")
    p.add_argument("--url-template", help="template XYZ proprio, ex.: https://.../{z}/{x}/{y}.jpg")
    p.add_argument("--token", help="chave/token do provedor de imagem")
    p.add_argument("--zoom", type=int, help="nivel de zoom dos tiles (padrao: maximo)")
    p.add_argument("--diametro-copa", type=float, default=6.0,
                   help="diametro medio de copa esperado, em metros (padrao: 6)")
    p.add_argument("--area-min", type=float, help="area minima de copa em m2")
    p.add_argument("--area-max", type=float, help="area maxima de copa em m2")
    p.add_argument("--modo", default="escuro", choices=["escuro", "verde", "brilho"],
                   help="escuro: copa verde e escura sobre pasto claro (padrao); "
                        "verde: copa verde sobre solo exposto; brilho: so por sombra")
    p.add_argument("--indice", default="exg", choices=["exg", "vari", "gli"],
                   help="indice de vegetacao usado no RGB (padrao: exg)")
    p.add_argument("--limiar-vegetacao", type=float,
                   help="limiar manual do indice de vegetacao (padrao: Otsu automatico)")
    p.add_argument("--sensibilidade", type=float, default=1.2,
                   help=">1 detecta mais copas (e mais falsos positivos); <1 detecta menos")
    p.add_argument("--amostras", type=int, default=6,
                   help="numero de parcelas para conferencia manual (0 desativa)")
    p.add_argument("--lado-parcela", type=float, default=100.0,
                   help="lado das parcelas de validacao, em metros (padrao: 100)")
    p.add_argument("--saida", default="resultado", help="pasta de saida (padrao: resultado)")
    args = p.parse_args(argv)

    from contagem_arvores import aoi as mod_aoi
    from contagem_arvores import deteccao, saidas

    saida = Path(args.saida)
    saida.mkdir(parents=True, exist_ok=True)

    print(f"[1/4] Lendo perimetro: {args.kml}")
    geom, nomes = mod_aoi.carregar_aoi(args.kml)
    ha = mod_aoi.area_hectares(geom)
    lon_min, lat_min, lon_max, lat_max = geom.bounds
    print(f"  area do poligono: {ha:.2f} ha")
    print(f"  bbox: {lon_min:.6f},{lat_min:.6f} ate {lon_max:.6f},{lat_max:.6f}")

    fonte = ""
    if args.imagem:
        caminho_tif = Path(args.imagem)
        if not caminho_tif.exists():
            print(f"ERRO: imagem nao encontrada: {caminho_tif}", file=sys.stderr)
            return 2
        fonte = str(caminho_tif)
        print(f"[2/4] Usando imagem informada: {caminho_tif}")
    elif args.baixar:
        from contagem_arvores import imagens

        print(f"[2/4] Baixando mosaico ({args.provedor})...")
        caminho_tif = imagens.baixar_mosaico(
            geom, saida / "mosaico.tif", provedor=args.provedor, zoom=args.zoom,
            token=args.token, url_template=args.url_template)
        fonte = imagens.PROVEDORES.get(args.provedor, {}).get("credito", args.provedor)
    else:
        print("ERRO: informe --imagem arquivo.tif ou --baixar.", file=sys.stderr)
        return 2

    print("[3/4] Detectando copas...")
    resultado = deteccao.detectar(
        caminho_tif, aoi=geom, diametro_copa=args.diametro_copa,
        area_min=args.area_min, area_max=args.area_max, modo=args.modo,
        indice=args.indice, limiar_vegetacao=args.limiar_vegetacao,
        sensibilidade=args.sensibilidade)

    print("[4/4] Gravando saidas...")
    saidas.escrever_kml(resultado, saida / "arvores.kml", nome=Path(args.kml).stem)
    saidas.escrever_geojson(resultado, saida / "arvores.geojson")
    saidas.escrever_csv(resultado, saida / "arvores.csv")
    saidas.salvar_conferencia(resultado, saida / "conferencia.png")
    if args.amostras:
        saidas.salvar_amostras(resultado, saida / "amostras", n=args.amostras,
                               lado_m=args.lado_parcela)
    saidas.escrever_relatorio(resultado, saida / "relatorio.txt",
                              nome_area=Path(args.kml).stem, fonte_imagem=fonte,
                              nomes=nomes[:5])

    print()
    print(f"  ARVORES DETECTADAS: {resultado.total}")
    print(f"  Area analisada....: {resultado.area_ha:.2f} ha")
    print(f"  Densidade.........: {resultado.densidade:.1f} arvores/ha")
    print(f"  Saidas em.........: {saida.resolve()}")
    print("  Abra 'arvores.kml' no Google Earth e confira as parcelas em 'amostras/'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
