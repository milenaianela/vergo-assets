# Levantamento Ambiental — Fazendas Campanelli

`Levantamento_Ambiental_Fazendas_Campanelli.xlsx` é o instrumento de coleta dos dados
ambientais das 20 fazendas próprias e 10 fazendas parceiras da planilha de origem.

## Abas

| Aba | Conteúdo |
|---|---|
| Instruções | Roteiro de consulta: órgão, portal, dado de entrada e documento a obter para cada item |
| Resumo por Imóvel | Uma linha por imóvel, com contagens automáticas das abas de detalhe |
| CAR | Uma linha por matrícula — nº do CAR, situação, RL, APP, passivo, PRA |
| Outorgas | Uma linha por outorga — DAEE/ANA, vazão, validade, situação |
| Autos e TCRA | Autos de infração, autos de imposição de penalidade, TCRA e TAC |
| Processos CETESB | Processos administrativos, exigências e prazos |
| Incêndios | Ocorrências, área atingida, origem, autuação e recuperação |
| Licenciamentos | LP/LI/LO, CADRI, autorizações de supressão e intervenção em APP |
| Base - Próprias / Base - Parceiras | Cópia intacta da planilha de origem |

## Preenchimento

- Células **amarelas** = preenchimento manual a partir da consulta oficial.
- Colunas de contagem no Resumo são fórmulas — não editar.
- As colunas de situação têm listas suspensas (aba oculta `Listas`).
- Nenhum dado ambiental foi presumido: os campos estão em branco até a consulta.

## Regerar o arquivo

```bash
pip install openpyxl
OUT=Levantamento_Ambiental_Fazendas_Campanelli.xlsx python3 gerar_planilha.py
```

`dados_base.json` guarda a estrutura extraída da planilha de origem (imóvel, município,
CCIR, matrículas e áreas).
