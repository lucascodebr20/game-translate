# Tradutor RPG Maker MV

Aplicação gráfica para traduzir jogos RPG Maker MV que armazenam dados em
`www/data/*.json`.

## Uso

1. Execute `Iniciar Tradutor.bat`.
2. Selecione a pasta do jogo, a pasta `www` ou `www/data`.
3. Confira a pasta de saída e clique em **Traduzir**.
4. Teste a tradução gerada. Use **Aplicar ao jogo (com backup)** somente depois
   de conferir o resultado.

Na primeira tradução, o modelo offline de idioma será baixado. As próximas
traduções usam o modelo já instalado.

O programa traduz diálogos, escolhas, textos rolantes, nomes e descrições do
banco de dados. Scripts, notas de plugins e comandos internos são ignorados.

## Modelos de tradução

Em **Configurações** é possível escolher o modelo usado:

| Modelo | Download | Quando usar |
|---|---|---|
| Argos Translate (padrão) | ~100 MB por idioma | O mais rápido. Bom para inglês. |
| NLLB-200 600M | 620 MB | Japonês direto, sem passar pelo inglês. De 4 a 7× mais lento. |
| NLLB-200 1.3B | 1,4 GB | A melhor qualidade, principalmente em japonês. De 7 a 13× mais lento. |

Os modelos NLLB-200 (Meta) usam a licença CC-BY-NC 4.0, que permite somente uso
não comercial. Eles são baixados na primeira tradução e ficam em
`%LOCALAPPDATA%\TradutorRPGMaker\models`. As traduções já feitas ficam em cache
em `%LOCALAPPDATA%\TradutorRPGMaker\translation_cache.sqlite3`, separadas por modelo.
