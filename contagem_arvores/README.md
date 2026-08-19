# Contagem de árvores por imagem de satélite a partir de um KML

Ferramenta de linha de comando que lê o perímetro de uma área (KML/KMZ/GeoJSON
exportado do Google Earth), analisa uma imagem de satélite RGB de alta resolução
e devolve **quantas árvores existem dentro do polígono**, com um ponto para cada
copa detectada.

## Instalação

```bash
pip install -r contagem_arvores/requirements.txt
```

## Uso

**Opção 1 — imagem própria já georreferenciada** (drone, ortofoto, Planet,
recorte exportado do QGIS). É a opção de melhor qualidade:

```bash
python -m contagem_arvores.contar_arvores fazenda.kml --imagem ortofoto.tif
```

**Opção 2 — baixar o mosaico de um provedor de tiles** que você tem licença
para usar:

```bash
python -m contagem_arvores.contar_arvores fazenda.kml --baixar --provedor esri
python -m contagem_arvores.contar_arvores fazenda.kml --baixar --provedor mapbox --token SEU_TOKEN
python -m contagem_arvores.contar_arvores fazenda.kml --baixar --url-template "https://.../{z}/{x}/{y}.jpg"
```

### Arquivo com várias camadas

KMZ exportado do Google Earth costuma trazer camadas empilhadas (talhões, SIGEF,
SICAR). Contar na união de todas daria um número errado — inspecione primeiro e
depois restrinja com `--camada`:

```bash
python -m contagem_arvores.inspecionar fazenda.kmz                  # lista as camadas
python -m contagem_arvores.inspecionar fazenda.kmz --tabela talhoes.csv
python -m contagem_arvores.inspecionar fazenda.kmz --mapa croqui.png
python -m contagem_arvores.inspecionar fazenda.kmz --extrair "SICAR - Fazendas" --saida sicar.kml
python -m contagem_arvores.inspecionar fazenda.kmz \
    --diferenca "SICAR - Fazendas" "TALHOES" --saida fora_dos_talhoes.kml

python -m contagem_arvores.contar_arvores fazenda.kmz --camada "SICAR - Fazendas" --imagem orto.tif
```

`--diferenca` é útil para isolar o que **não** é área cultivada (APP, reserva
legal, carreadores, sede) — normalmente é ali que estão as árvores.

### Parâmetros que mais importam

| Parâmetro | Para que serve |
|---|---|
| `--diametro-copa 6` | diâmetro médio de copa esperado, em metros. **É o ajuste principal.** Eucalipto adulto ~4 m, árvore isolada de pasto 8–12 m, café ~2 m |
| `--sensibilidade 1.2` | acima de 1,2 detecta mais copas (e mais falsos positivos); abaixo detecta menos |
| `--modo escuro` | `escuro`: copa verde e mais escura que o pasto claro (padrão, típico de pasto e cerrado). `verde`: copa verde sobre solo exposto ou pasto seco. `brilho`: separa só por sombra, ignorando cor |
| `--area-min` / `--area-max` | limites de área de copa em m², para descartar arbustos e manchas grandes de mata contínua |
| `--camada "NOME"` | usa só uma pasta do KML, em vez da união de todas |
| `--zoom 19` | nível de zoom dos tiles quando usa `--baixar` |
| `--amostras 6` | número de parcelas recortadas para conferência manual |

### Saídas (pasta `resultado/`)

- `arvores.kml` — **abre direto no Google Earth**, um ponto por árvore
- `arvores.geojson` / `arvores.csv` — para QGIS, ArcGIS ou planilha
- `conferencia.png` — imagem toda com cada copa circulada
- `amostras/` — parcelas de 100 × 100 m recortadas em duas versões (limpa e com
  as detecções) mais `validacao.csv` para você contar no olho e comparar
- `relatorio.txt` — total, densidade (árvores/ha), diâmetro médio de copa e
  todos os parâmetros usados

## Como funciona

1. Índice de vegetação sobre o RGB (ExG, VARI ou GLI) separa vegetação de solo,
   telhado, água e estrada.
2. Mapa de "copa" conforme o contraste escolhido em `--modo`.
3. Filtro *top-hat* com elemento do tamanho da copa realça só o que tem escala de
   árvore e remove o fundo de baixa frequência.
4. Máximos locais separados por, no mínimo, um raio de copa geram as sementes.
5. *Watershed* a partir das sementes delimita cada copa individualmente.
6. Filtro por área mínima/máxima de copa e recorte pelo polígono do KML.

Não precisa de GPU, nem de dados de treinamento, nem de internet quando a imagem
já está em disco.

Imagem acima de 40 milhões de pixels (≈ 360 ha a 0,30 m/pixel) é processada em
blocos de 4096 px com sobreposição, e as copas repetidas na emenda dos blocos são
removidas por distância — dá para rodar uma fazenda inteira sem estourar a
memória. A imagem de conferência sai reduzida nesse caso; as parcelas de
`amostras/` continuam em resolução original, lidas direto do GeoTIFF.

## Precisão medida

Validação em cena sintética de pasto (0,30 m/pixel, 7,3 ha, sombras e estrada de
terra, verdade de campo conhecida):

| Cenário | Verdade | Detectado | Precisão | Recall | Erro na contagem |
|---|---|---|---|---|---|
| Árvores isoladas (espaçamento ≥ 8 m) | 107 | 106 | 100 % | 99 % | −0,9 % |
| Mesma cena, processada em blocos | 107 | 108 | 98 % | 99 % | +0,9 % |
| Copas encostadas / adensadas | 112 | 102 | — | — | −8,9 % |

Em imagem real o erro é maior que isso. Expectativa realista:

- **pasto com árvores isoladas, eucalipto, café, pomar, SAF em linha** —
  erro típico de 5 % a 15 %, resultado utilizável;
- **regeneração, cerrado adensado, mata com dossel fechado** — a contagem
  individual por RGB de satélite **não é confiável** (copas fundidas e indivíduos
  suprimidos sob o dossel não aparecem). Nesse caso use a ferramenta para estimar
  **área de cobertura de copa**, e faça a densidade por parcelas de campo,
  drone ou LiDAR.

Regra prática de resolução: a copa precisa ter pelo menos ~10 pixels de diâmetro.
Com imagem de 0,30 m/pixel isso significa copas a partir de ~3 m de diâmetro.

## Limitações e cuidados

- A contagem automática é uma **estimativa**. Para laudo, inventário florestal ou
  processo de autorização de supressão, valide com as parcelas geradas em
  `amostras/` e registre o fator de correção no relatório.
- Copas encostadas viram uma árvore só; árvore sob copa maior não é vista.
- A data da imagem importa: mosaico de satélite pode ter 1 a 3 anos de defasagem,
  e imagem de estação seca com pasto amarelado muda o contraste (use `--modo verde`).
- **Licenciamento:** o Google Earth / Google Maps não permite raspagem automática
  de tiles. Para trabalho comercial use imagem própria, Google Maps Static API com
  chave, Mapbox com token, Esri conforme seu contrato ArcGIS, ou as imagens
  gratuitas do INPE (CBERS-4A, ~2 m). O KML do Google Earth pode ser usado
  livremente — a restrição é só sobre baixar a imagem.

## Fluxo recomendado no escritório

1. Desenhar/exportar o perímetro no Google Earth → `fazenda.kml`.
2. Rodar com `--diametro-copa` estimado na foto e `--amostras 8`.
3. Abrir `conferencia.png` e ajustar `--diametro-copa` / `--sensibilidade` até os
   círculos baterem com as copas.
4. Contar manualmente as parcelas de `amostras/`, preencher `contagem_manual` em
   `validacao.csv` e calcular o fator de correção.
5. Aplicar o fator ao total e entregar `arvores.kml` junto com o relatório.
