# Tradutor de Jogos

Aplicação gráfica para traduzir jogos RPG Maker MV que armazenam dados em
`www/data/*.json`.

Também aceita jogos HTML/JavaScript (NW.js) com `www/index.html` e `www/js`.
Selecione a pasta do jogo ou `www`;
o app detecta Inglês ou Japonês pelos textos do jogo. A saída contém
uma cópia de `www`, com os textos estáticos dos arquivos JavaScript
e HTML traduzidos. **Aplicar ao jogo (com backup)** copia essa saída de volta
para `www` e guarda uma cópia da pasta original.

Nesse formato, textos em imagens, atributos HTML e templates JavaScript com
`${expressões}` não são traduzidos. Comentários e código fora das strings são
preservados. Confira o jogo antes de aplicar: strings também podem representar
valores usados pela lógica de uma engine personalizada.
Para inglês, são extraídos campos de diálogo e rótulos conhecidos, atribuições
de texto da interface e chamadas de avisos; identificadores e caminhos de
arquivos ficam preservados. Engines com outros campos podem exigir adaptação.

## Uso

### Visual Novel Maker

Selecione a pasta do jogo. O aplicativo
detecta os dados em `resources/app` e o idioma de origem automaticamente.
Também é possível selecionar diretamente `resources/app` ou sua pasta `data`.
Escolha Português e clique em **Traduzir**.

A saída é uma cópia de `resources/app`, com os diálogos, escolhas e textos
localizáveis traduzidos. Os arquivos `*.json.js` são decodificados e
recodificados no formato usado pelo jogo. Identificadores, scripts e códigos
como `{GT:Input Text Result}` são preservados. Textos em imagens e strings
embutidas nos scripts da interface não são traduzidos.

**Aplicar ao jogo (com backup)** copia a saída para `resources/app` e guarda
a pasta original em `resources/app_backup_DATA_HORA`. Feche o jogo antes
de aplicar. Para restaurar, recupere a pasta `app` desse backup.
Confira no jogo a tradução e o tamanho dos textos nas caixas de diálogo.

O menu lateral **Compatibilidade** permite ativar japonês para programas
antigos no Windows. Antes da alteração, o tradutor salva o idioma regional
e as páginas de código atuais. **Restaurar anterior** recupera essa configuração,
inclusive o modo UTF-8 se estava habilitado. O Windows não oferece um modo
automático para essa opção; por isso o botão restaura o estado anterior.

As duas ações pedem permissão de administrador e exigem reinicialização manual
do Windows. A alteração afeta os programas antigos de todo o sistema.
O tradutor desativa o modo UTF-8 ao ativar japonês, sem mudar o idioma da interface
do Windows. O backup fica em `%LOCALAPPDATA%\TradutorRPGMaker\windows_locale.json`;
não apague esse arquivo enquanto a compatibilidade estiver ativada.

### Jogos PAC

Selecione a pasta que contém `srp.pac`. O tradutor aceita a variante de
cenários suportada pelo leitor e detecta inglês ou japonês pelos diálogos.
A saída contém apenas `srp.pac`; **Aplicar ao jogo (com backup)** substitui
esse arquivo e guarda o original em uma pasta de backup. Para restaurar,
copie o `srp.pac` do backup de volta para a pasta do jogo, com o jogo fechado.

São traduzidos os registros conhecidos de diálogo e narração. Nomes dos
personagens, códigos de voz, comandos, entradas de sistema e variantes
desconhecidas permanecem intactos. Textos em imagens, menus e opções dentro
de comandos ainda não são traduzidos. Outros jogos com extensão `.pac`
podem usar formatos diferentes e não são automaticamente compatíveis.

O formato usa Shift-JIS: acentos latinos são convertidos para letras simples
(por exemplo, `não` vira `nao`), e os textos recebem quebras de linha.
Não foi implementada uma alteração no executável para exibir português
acentuado. Confira a tradução no jogo, incluindo o tamanho das caixas de
texto, antes de continuar uma partida. A saída PAC é um patch de dados e
precisa ser aplicada ao jogo para ser usada.

O utilitário `inspect_pac.py` permite extrair os textos para inspeção:
`python inspect_pac.py "C:\caminho\srp.pac" "output\textos.json"`.

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
