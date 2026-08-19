#!/usr/bin/env python3
"""Inspeciona um KML/KMZ: lista camadas, exporta tabela de atributos e recortes.

Util quando o arquivo do Google Earth tem varias camadas empilhadas (talhoes,
SIGEF, SICAR) - contar arvores na uniao de tudo daria um numero errado.

  python -m contagem_arvores.inspecionar arquivo.kmz
  python -m contagem_arvores.inspecionar arquivo.kmz --tabela talhoes.csv
  python -m contagem_arvores.inspecionar arquivo.kmz --extrair "SIGEF - Fazendas" --saida sigef.kml
  python -m contagem_arvores.inspecionar arquivo.kmz --diferenca "SICAR - Fazendas" "TALHOES" --saida resto.kml
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def desenhar_mapa(arquivo, saida, dpi=140):
    """Croqui das camadas do KML, uma cor por camada."""
    import math

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    from contagem_arvores.aoi import carregar_placemarks

    registros = carregar_placemarks(arquivo)
    camadas = []
    for r in registros:
        if r.get("camada") not in camadas:
            camadas.append(r.get("camada"))
    cores = ["#2e7d32", "#1565c0", "#ef6c00", "#6a1b9a", "#c62828", "#00838f"]

    fig, ax = plt.subplots(figsize=(11, 9))
    for r in registros:
        cor = cores[camadas.index(r.get("camada")) % len(cores)]
        partes = list(r["geom"].geoms) if hasattr(r["geom"], "geoms") else [r["geom"]]
        for p in partes:
            x, y = p.exterior.xy
            ax.fill(x, y, facecolor=cor, alpha=0.18, edgecolor=cor, linewidth=0.7)

    lat = sum(ax.get_ylim()) / 2
    ax.set_aspect(1 / math.cos(math.radians(lat)))
    ax.set_xlabel("longitude"); ax.set_ylabel("latitude")
    ax.set_title(f"{Path(arquivo).stem} - camadas do KML")
    ax.legend(handles=[Patch(facecolor=cores[i % len(cores)], alpha=0.4,
                             edgecolor=cores[i % len(cores)], label=c or "(sem pasta)")
                       for i, c in enumerate(camadas)], loc="best", fontsize=8)
    ax.grid(alpha=0.25, linewidth=0.4)
    fig.tight_layout()
    fig.savefig(saida, dpi=dpi)
    plt.close(fig)
    return Path(saida)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Inspeciona camadas de um KML/KMZ.")
    p.add_argument("arquivo", help="arquivo .kml ou .kmz")
    p.add_argument("--tabela", help="CSV com um registro por placemark e seus atributos")
    p.add_argument("--extrair", metavar="CAMADA", help="exporta uma camada para KML")
    p.add_argument("--diferenca", nargs=2, metavar=("CAMADA_A", "CAMADA_B"),
                   help="exporta CAMADA_A menos CAMADA_B (ex.: imovel menos talhoes)")
    p.add_argument("--saida", help="arquivo KML de saida para --extrair/--diferenca")
    p.add_argument("--mapa", help="PNG com o croqui das camadas (ex.: mapa.png)")
    args = p.parse_args(argv)

    from shapely.ops import unary_union

    from contagem_arvores import saidas
    from contagem_arvores.aoi import (area_hectares, carregar_placemarks,
                                      listar_camadas)

    camadas = listar_camadas(args.arquivo)
    print(f"Arquivo: {args.arquivo}")
    print("Camadas:")
    for c in camadas:
        print(f"{'  ' * (c['nivel'] + 1)}- {c['nome']}: {c['placemarks']} placemarks, "
              f"{c['poligonos']} poligonos, {c['area_ha']:.1f} ha (uniao)")

    if args.tabela:
        registros = carregar_placemarks(args.arquivo)
        campos = ["camada", "nome", "n_poligonos", "area_ha_calculada"]
        extras = []
        for r in registros:
            for k in r["atributos"]:
                if k not in extras:
                    extras.append(k)
        with Path(args.tabela).open("w", newline="", encoding="utf-8") as f:
            escritor = csv.DictWriter(f, fieldnames=campos + extras)
            escritor.writeheader()
            for r in registros:
                linha = {"camada": r.get("camada", ""), "nome": r["nome"], "n_poligonos": r["n_poligonos"],
                         "area_ha_calculada": round(r["area_ha"], 4)}
                linha.update(r["atributos"])
                escritor.writerow(linha)
        print(f"\nTabela gravada: {args.tabela} ({len(registros)} registros)")

    if args.extrair:
        registros = carregar_placemarks(args.arquivo, args.extrair)
        saida = Path(args.saida or f"{args.extrair}.kml")
        saidas.escrever_kml_poligonos([(r["geom"], r["nome"]) for r in registros],
                                      saida, nome=args.extrair)
        total = area_hectares(unary_union([r["geom"] for r in registros]))
        print(f"\nCamada '{args.extrair}': {len(registros)} feicoes, {total:.1f} ha "
              f"-> {saida}")

    if args.mapa:
        desenhar_mapa(args.arquivo, args.mapa)
        print(f"\nMapa gravado: {args.mapa}")

    if args.diferenca:
        nome_a, nome_b = args.diferenca
        a = unary_union([r["geom"] for r in carregar_placemarks(args.arquivo, nome_a)])
        b = unary_union([r["geom"] for r in carregar_placemarks(args.arquivo, nome_b)])
        resto = a.difference(b)
        saida = Path(args.saida or "diferenca.kml")
        saidas.escrever_kml_poligonos([(resto, f"{nome_a} menos {nome_b}")], saida,
                                      nome=f"{nome_a} menos {nome_b}")
        print(f"\n{nome_a} ({area_hectares(a):.1f} ha) menos {nome_b} "
              f"({area_hectares(b):.1f} ha) = {area_hectares(resto):.1f} ha -> {saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
