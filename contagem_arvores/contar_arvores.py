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


def _por_feicao(args, caminho_tif, saida, fonte, geom_total) -> int:
    """Conta talhao a talhao e consolida numa tabela.

    Com `caminho_tif=None` o mosaico e baixado por feicao - e o unico jeito
    viavel de rodar uma fazenda inteira, ja que um mosaico unico de milhares de
    hectares passa de dezenas de milhares de tiles."""
    import csv
    import random

    from contagem_arvores import aoi as mod_aoi
    from contagem_arvores import deteccao, saidas

    registros = mod_aoi.carregar_placemarks(args.kml, camada=args.camada)
    print(f"[3/4] Detectando copas em {len(registros)} feicoes...")

    linhas, todas, resultados = [], [], []
    campos_extras = []
    for i, r in enumerate(registros, start=1):
        print(f"  ({i}/{len(registros)}) {r['nome'] or '-'} - {r['area_ha']:.1f} ha",
              flush=True)
        if caminho_tif is None:
            from contagem_arvores import imagens

            alvo = saida / "mosaicos" / f"{i:03d}_{(r['nome'] or 'feicao')}.tif"
            if alvo.exists():
                tif_feicao = alvo
            else:
                try:
                    tif_feicao = imagens.baixar_mosaico(
                        r["geom"], alvo, provedor=args.provedor, zoom=args.zoom,
                        token=args.token, url_template=args.url_template,
                        verboso=False)
                except Exception as erro:
                    print(f"      falhou o download: {erro}")
                    continue
        else:
            tif_feicao = caminho_tif
        try:
            res = deteccao.detectar(
                tif_feicao, aoi=r["geom"], diametro_copa=args.diametro_copa,
                area_min=args.area_min, area_max=args.area_max, modo=args.modo,
                indice=args.indice, limiar_vegetacao=args.limiar_vegetacao,
                sensibilidade=args.sensibilidade, verboso=False)
        except ValueError as erro:      # feicao fora da imagem
            print(f"      ignorada: {erro}")
            continue
        resultados.append((r, res))
        for a in res.arvores:
            copia = dict(a)
            copia["feicao"] = r["nome"]
            todas.append(copia)
        linha = {
            "feicao": r["nome"], "area_ha_poligono": round(r["area_ha"], 2),
            "area_ha_analisada": round(res.area_ha, 2), "arvores": res.total,
            "arvores_por_ha": round(res.densidade, 2),
        }
        for k, v in r["atributos"].items():
            linha[k] = v
            if k not in campos_extras:
                campos_extras.append(k)
        linhas.append(linha)

    print("[4/4] Gravando saidas...")
    campos = ["feicao", "area_ha_poligono", "area_ha_analisada", "arvores",
              "arvores_por_ha"] + campos_extras
    with (saida / "por_feicao.csv").open("w", newline="", encoding="utf-8") as f:
        escritor = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        escritor.writeheader()
        escritor.writerows(linhas)

    class _Consolidado:
        arvores = todas
        area_ha = sum(l["area_ha_analisada"] for l in linhas)
        resolucao_m = resultados[0][1].resolucao_m if resultados else 0.0
        total = len(todas)
        densidade = total / area_ha if area_ha else 0.0
        parametros = dict(resultados[0][1].parametros) if resultados else {}

    saidas.escrever_kml(_Consolidado, saida / "arvores.kml", nome=Path(args.kml).stem)
    saidas.escrever_geojson(_Consolidado, saida / "arvores.geojson")
    saidas.escrever_csv(_Consolidado, saida / "arvores.csv")
    saidas.escrever_relatorio(_Consolidado, saida / "relatorio.txt",
                              nome_area=Path(args.kml).stem, fonte_imagem=fonte,
                              nomes=[str(l["feicao"]) for l in linhas[:5]])

    if args.amostras and resultados:
        sorteados = random.Random(42).sample(resultados,
                                             min(args.amostras, len(resultados)))
        for i, (r, res) in enumerate(sorteados, start=1):
            saidas.salvar_amostras(res, saida / "amostras" / f"{i:02d}_{r['nome']}",
                                   n=1, lado_m=args.lado_parcela)

    print()
    print(f"  ARVORES DETECTADAS: {len(todas)} em {len(linhas)} feicoes")
    print(f"  Area analisada....: {_Consolidado.area_ha:.2f} ha")
    print(f"  Densidade.........: {_Consolidado.densidade:.1f} arvores/ha")
    print(f"  Tabela por feicao.: {(saida / 'por_feicao.csv').resolve()}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Contagem de arvores por imagem de satelite a partir de um KML.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("kml", help="arquivo .kml, .kmz ou .geojson com o perimetro da area")
    p.add_argument("--camada", help="usar apenas uma camada/pasta do KML "
                   "(veja com: python -m contagem_arvores.inspecionar arquivo.kmz)")
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
    p.add_argument("--por-feicao", action="store_true",
                   help="conta separadamente cada talhao/feicao da camada e gera "
                        "uma tabela com o total de cada um")
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
    geom, nomes = mod_aoi.carregar_aoi(args.kml, camada=args.camada)
    ha = mod_aoi.area_hectares(geom)
    lon_min, lat_min, lon_max, lat_max = geom.bounds
    if args.camada:
        print(f"  camada: {args.camada}")
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
    elif args.baixar and args.por_feicao:
        from contagem_arvores import imagens

        fonte = imagens.PROVEDORES.get(args.provedor, {}).get("credito", args.provedor)
        print(f"[2/4] Mosaico sera baixado por feicao ({args.provedor})")
        return _por_feicao(args, None, saida, fonte, geom)
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

    if args.por_feicao:
        return _por_feicao(args, caminho_tif, saida, fonte, geom)

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
