# Validação com cena sintética

Gera uma cena de pasto de 300 × 300 m a 0,30 m/pixel com número de árvores
conhecido (copas, sombras e uma estrada de terra para testar falso positivo),
roda o detector e compara com a verdade de campo.

```bash
cd contagem_arvores/testes
python gerar_cena_teste.py                      # cria cena.tif e area.kml
PYTHONPATH=../.. python -m contagem_arvores.contar_arvores area.kml \
    --imagem cena.tif --diametro-copa 6.5 --saida saida_teste
python avaliar.py saida_teste/arvores.geojson   # precisão, recall, F1
```

Resultado esperado com os parâmetros acima: 106 detectadas para 107 reais,
precisão 100 %, recall 99 %, nenhum falso positivo na estrada.
