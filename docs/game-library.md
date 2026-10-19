# Biblioteca de jogos — Guition 10,1 polegadas

Implementação experimental para o Guition JC8012P4A1C. Inclui uma interface
nativa de toque no display e uma interface de conferência no navegador.
Não foi validada em um Guition ou MiSTer físico durante o desenvolvimento.

## O que o usuário pode fazer

- Tocar em **Biblioteca**, no canto superior direito do monitor.
- Escolher um sistema do microSD do **MiSTer** e navegar por suas pastas.
- Ver na tela **Sistemas** somente sistemas com jogos reconhecidos pelo Remote,
  incluindo jogos em subpastas e ZIPs. Pastas vazias e pastas só com capas ou
  documentos ficam fora da lista; o Arcade aparece quando há MRAs.
- Ver seis capas por página, escolher jogos e iniciar pelo toque.
- Buscar pelo nome **dentro da pasta atual**, com teclado na tela.
- Salvar e remover favoritos; a lista permanece após reiniciar o servidor.
- Cancelar a seleção ou confirmar explicitamente a troca de jogo.
- Voltar ao monitor original pelo botão **Monitor**.

Não é uma tela de configuração do boot automático ao ligar. **Iniciar jogo**
solicita o carregamento imediato do core e do jogo no MiSTer ligado. A resposta
confirma que o Remote aceitou o pedido; verifique o resultado na TV.

## Requisitos

1. Guition JC8012P4A1C de 10,1 polegadas, com microSD, Wi-Fi e configuração
   `config.ini` já utilizada no MiSTer Monitor.
2. MiSTer na mesma rede, com servidor Monitor e **MiSTer Remote (`remote.sh`)**
   atualizado e em execução na porta 8182. O Remote é uma dependência explícita.
3. ROMs nas pastas reconhecidas pelo Remote, sob `/media/fat/games`, ou MRAs
   sob `/media/fat/_Arcade`. Esta versão não inclui jogos em USB/NAS nem atalhos
   MGL fora dessas árvores. Links simbólicos que saem dessas árvores são omitidos.
4. Para capas, instalar o **MiSTer Artwork Pack / Box Art** no MiSTer via
   Update All. A biblioteca usa `docs/<System>/Artwork` e seu `index.tsv`.
   Sem imagem correspondente, mostra **Sem capa**; o jogo continua selecionável.

O Remote identifica os tipos de arquivo e o core correto. ZIPs aparecem como
pastas: abra o ZIP e selecione o jogo dentro dele. Nem todos os formatos, BIOS
ou esquemas de discos são automaticamente inicializáveis; erros do Remote
aparecem na interface. A seleção de core alternativo não faz parte desta versão.

A biblioteca não faz scraping de toda a coleção, não lê o microSD do display
como se fosse o do MiSTer e não altera ROMs, BIOS, saves ou core binaries.

## Atualização: somente sistemas com jogos

Esta branch agora usa a seleção solicitada: **SNES, Mega Drive/Genesis,
Master System, TurboGrafx-16/TG16, NES, N64 e PSX**. Mega Drive e Genesis
representam o mesmo sistema; TurboGrafx, TG16 e TGFX16 também. Os nomes de
pasta SMS/MasterSystem, MegaDrive/Genesis e TGFX16/TG16/PC Engine são aceitos,
com diferenças de maiúsculas, espaços e hífens normalizadas. Mega CD,
TurboGrafx-CD e SuperGrafx permanecem sistemas separados, fora desta seleção.

A seleção é aplicada antes de verificar ROMs, subpastas e ZIPs. Assim o
servidor deixa de percorrer os sistemas excluídos, reduzindo trabalho e tempo
de abertura da tela Sistemas. O ganho real depende da coleção e deve ser
medido no MiSTer; a medição anterior foi de 10,53 s antes desta seleção.
Dentro dos sete sistemas, o filtro continua ocultando os que estiverem vazios.
A mesma seleção vale para os favoritos exibidos, preservando os favoritos
de sistemas ocultos no arquivo de estado.

Para uma biblioteca já instalada, substitua apenas
`Scripts/.config/mister_monitor/game_library.py` pela versão desta branch,
guardando uma cópia do arquivo anterior. Execute **MiSTer_Monitor** no menu
Scripts para reiniciar o servidor e toque em **Atualizar** na biblioteca.
A atualização vale para o site e para a tela Guition com o firmware da
biblioteca já instalado; não exige nova gravação do display.

O servidor verifica a presença de jogos antes de calcular a quantidade de
sistemas e as páginas. A verificação percorre as pastas e ZIPs pelo Remote e
para no primeiro jogo reconhecido de cada sistema. O botão **Atualizar** refaz
a consulta, incluindo alterações recentes na coleção. Coleções com muitas
subpastas podem levar mais tempo para abrir a tela **Sistemas**.

O reconhecimento segue os tipos de arquivo informados pelo Remote; não
garante que o conteúdo de cada arquivo seja um jogo válido ou que suas BIOS
estejam instaladas. Erros de consulta aparecem como erro, em vez de fazer um
sistema parecer vazio. A navegação dentro das pastas mantém seu comportamento.

Os 16 testes do servidor passaram localmente após essa alteração, cobrindo
sistemas vazios, imagens sem ROMs, subpastas, ZIPs vazios e com jogos, Arcade,
paginação, atualização da coleção e ciclos/escapes por links simbólicos.
O filtro ainda precisa de conferência na coleção do usuário.

Após a seleção dos sete sistemas, os 20 testes do servidor passaram localmente,
incluindo a verificação de que sistemas excluídos não são consultados. Para
personalizar esta seleção no servidor, ajuste `DEFAULT_SYSTEMS` em
`game_library.py`; `systems=None` na classe permite o modo sem seleção.

## Cache e carregamento progressivo

Esta atualização de desempenho exige **o servidor, o app.js e o firmware**
novos. A seleção dos sete sistemas é mantida.

- O servidor mantém as listas por 60 segundos, em até 32 entradas e 4 MiB
  de JSON. Paginação e buscas reutilizam a mesma lista. Consultas simultâneas
  compartilham a leitura; favoritos são aplicados depois, sem ficarem obsoletos.
- **Atualizar** envia `refresh=1` e limpa o cache das listas antes de consultar
  novamente. Reiniciar o servidor também limpa esse cache de memória.
- No Guition, uma tarefa HTTP busca páginas e capas sem desenhar nem acessar
  o microSD. A tarefa da interface processa o toque, grava as capas recebidas
  e decodifica uma imagem por passagem. Respostas de páginas abandonadas são
  descartadas por uma geração de navegação; a fila guarda só a navegação mais
  recente. Sair para **Monitor** continua disponível durante os downloads.
- As capas ficam em `/library-cache-v1/` no microSD **da tela**, entre visitas
  e reinícios: até 128 JPEGs ou 16 MiB, mais um temporário de até 1 MiB durante
  a gravação. Ao atingir o limite, o firmware remove um JPEG do próprio cache.
  Arquivos fora desse cache não são removidos. Gravações incompletas não viram
  capas válidas. O botão **Atualizar** também descarta as capas da página visível.
- Sem microSD funcional, os nomes continuam disponíveis e aparece **Sem microSD**.
  A primeira visita ainda depende da rede; as seguintes podem usar as capas
  locais. A consulta inicial do catálogo ainda pode levar tempo. Salvar
  favoritos e solicitar lançamento continuam usando requisições síncronas.

Os 26 testes Python e o teste C++ do cache passaram localmente. O teste C++
usa o mesmo `LibraryCoverCache.h` do firmware com um adaptador de SD em memória
para verificar limites, descarte de arquivos, isolamento de caminhos e falhas
de escrita/rename. A compilação ESP32 e a validação física continuam necessárias;
o teste em memória não mede a latência real da rede, do cartão ou do JPEG.

## Instalação do servidor

Faça uma cópia da instalação atual de Monitor antes de extrair os arquivos.
Para preservar uma cópia automática, coloque o pacote numa pasta temporária
do cartão, por exemplo `/media/fat/monitor-library-package`, sem sobrepor
`/media/fat/Scripts` ainda. Execute por SSH:

```sh
bash /media/fat/monitor-library-package/MiSTer/Scripts/Install_Monitor_Library.sh
```

O instalador verifica o Remote, guarda o servidor anterior em
`Scripts/.config/mister_monitor/library-backup-<data>`, copia apenas o servidor
e a biblioteca e preserva suas credenciais e demais arquivos. Execute
**MiSTer_Monitor** no menu Scripts para reiniciar o servidor.

Alternativa manual: copie `mister_status_server.py`, `game_library.py` e a pasta
`library/` deste pacote para `Scripts/.config/mister_monitor/` do MiSTer.
Mantenha `ra_status.py`, credenciais e arquivos existentes. Reinicie o Monitor.

Confira primeiro no navegador:

```text
http://<IP-do-MiSTer>:8081/library
```

Se aparecer o aviso para iniciar o Remote, execute `remote.sh` pelo menu
Scripts e habilite seu serviço. A navegação não exige gerar índice de busca.

## Instalação do firmware

O firmware corrigido aguarda até **60 segundos** pela resposta HTTP da
biblioteca (antes, 10 segundos). Isso acomoda a verificação de sistemas com
jogos em cartões cuja consulta ultrapasse 10 segundos. As mensagens distinguem
tempo limite, erro de conexão, resposta sem tamanho, resposta grande demais,
transferência incompleta e JSON inválido. O limite de cada página continua em
24 KiB; a quantidade de jogos exibida por página permanece em seis.
O limite de 60 segundos é mantido nesta versão com cache. Enquanto consulta
o servidor, a tela mostra **Lendo o microSD...**; páginas e capas são buscadas
em uma tarefa separada, enquanto os botões continuam sendo processados.

Os builds têm variantes diferentes de chip; use a variante correta:

| Artefato | Hardware |
|---|---|
| `guition-library-prev3` | ESP32-P4 anterior à revisão v3.00 |
| `guition-library-postv3` | ESP32-P4 v3.00 ou posterior, normalmente etiqueta `-V3` |

Consulte a identificação no dispositivo ou no esptool; não escolha pela revisão
do painel. `panel_rev=v2` continua sendo uma configuração separada, preservada
no `config.ini`. As variantes de chip não são intercambiáveis.

Com Monitor 2.12.0 e partições OTA, abra no navegador
`http://<IP-do-display>:8080/update` e envie o arquivo **app-only**
`mister_monitor_Guition10inch.ino.bin` da variante correta. O arquivo
`.ino.merged.bin` inclui bootloader e partições, serve para flash por cabo
no endereço `0x0`, e **não** deve ser enviado à atualização OTA.
Para instalações antigas, siga [installation.md](installation.md) usando cabo
na porta USB UART, com a mesma variante de chip do dispositivo.

Este build não contém as credenciais privadas ScreenScraper do autor original.
As capas locais funcionam; as funções ScreenScraper exigem credenciais próprias
de desenvolvedor e de usuário no `config.ini`, conforme a configuração original.

O build da biblioteca desabilita ofertas automáticas de firmware oficial,
para que uma atualização upstream não remova a função. Upload manual `.bin`
continua disponível. O Update All ainda pode substituir o **servidor**; nesse
caso reinstale os arquivos deste pacote. Não há uma base Downloader própria.

## Compilar a partir do código

O workflow **Guition game library** compila as duas variantes, executa os testes
do servidor e disponibiliza os arquivos como artefatos do GitHub Actions.
Ele não precisa das credenciais privadas do repositório original.

```sh
arduino-cli core install esp32:esp32@3.3.12
arduino-cli lib install 'M5GFX@0.2.33' 'JPEGDEC@1.8.4' 'PNGdec@1.1.6' 'ArduinoJson@7.4.3'
```

Crie `mister_monitor_Guition10inch/ss_credentials.h` com os valores de
desenvolvedor próprios, ou os seguintes valores vazios para usar capas locais:

```cpp
#pragma once
#define SS_DEV_ID_EMBEDDED ""
#define SS_DEV_PASS_EMBEDDED ""
```

```sh
arduino-cli compile --jobs 2 \
  --fqbn 'esp32:esp32:esp32p4:ChipVariant=prev3,PSRAM=enabled,FlashMode=qio,FlashFreq=80,FlashSize=16M,PartitionScheme=app3M_fat9M_16MB' \
  --output-dir build/library-prev3 mister_monitor_Guition10inch
```

Para v3, troque `ChipVariant=prev3` por `ChipVariant=postv3` e o diretório de
saída por `build/library-postv3`.

## Estado desta entrega

- Nove testes Python passaram, incluindo resolução e entrega HTTP da capa pelo
  Artwork Pack, paginação, favoritos persistentes e lançamento confirmado.
- O fluxo JavaScript passou em teste de DOM com navegação, cancelamento,
  favoritos e pedido de lançamento. Não houve renderização em navegador real.
- O sketch completo passou em verificação de tipos (`-fsyntax-only`) com GCC
  RISC-V do core ESP32 3.3.12, tanto para `prev3` quanto para `postv3`.
- Compilação completa, montagem e linkedição das variantes `prev3` e `postv3`
  concluídas com sucesso no GitHub Actions em 18/10/2026, junto dos testes do servidor.
- [Execução verificada e binários](https://github.com/gabrieltalamoni/MiSTer_monitor/actions/runs/39140187820).
  Fonte compilada: commit `9f5b6af3386133778adff9e29abac4adb45b1e87` da branch
  `feature/guition-game-library` deste fork.
- Os artefatos contêm imagens app-only para OTA e merged para flash por cabo.
  Esta atualização da documentação não altera o código compilado.
- Não houve teste em MiSTer/Guition físico, nem acesso à coleção real do usuário.

## Verificação

```sh
python3 -m unittest discover -s tests -v
python3 tools/check_server.py
node --check MiSTer/Scripts/.config/mister_monitor/library/app.js
```

Os testes usam cartão temporário e um Remote simulado; cobrem paginação,
busca, pastas grandes, favoritos persistentes, isolamento do cartão, confirmação,
HTTP e preservação das rotas existentes. Não comprovam o boot no FPGA.

Validação física pendente: toque nos botões com sua revisão de painel, imagens
e uso de memória reais, reconexão de Wi-Fi e lançamento de ROM simples, ZIP,
MRA e mídia de CD suportada pelo Remote. Depois confirme saves e BIOS na TV.

## Referências de integração

- [MiSTer Remote: instalação](https://github.com/wizzomafizzo/mrext/blob/main/docs/remote.md)
- [API Remote: `games/view` e `games/launch`](https://github.com/wizzomafizzo/mrext/blob/main/docs/remote-api.md)
- [Formato atual da listagem Remote](https://github.com/wizzomafizzo/mrext/blob/main/cmd/remote/games/browse.go)
- [MiSTer Artwork Pack](https://github.com/chipster6502/MiSTer_artwork_pack)

## Installed RetroAchievements launchers and original display artwork

The library now prefers an installed `_RA_Cores/<system>.mgl` for its seven
selected systems. Genesis maps to `MegaDrive.mgl`, TGFX16 to
`TurboGrafx16.mgl`, and the remaining names are SNES, SMS, NES, N64 and PSX.
Before launch it asks `GET /api/systems/<id>/rbfs` to confirm the exact MGL
and an `RA_` setname; it sends that MGL as `rbf` to `games/launch`. An installed
but unrecognized RA launcher is an explicit error, never a silent stock-core
fallback. Where no RA MGL is installed the existing standard launch remains.
No cores, MiSTer.ini, main binary or credentials are installed or changed.

On the Guition, a game first reuses the original monitor's `findGameImage`
cache, including JPEG and PNG and friendly core names. It never deletes files
from that cache. Then it checks the library's bounded private cache, then the
MiSTer Artwork Pack. HTTP cover transfers now allow 30-second reads and decode
chunked transfer encoding with `writeToStream`, into a bounded PSRAM buffer.
The UI continues handling touch while network work runs. Page requests and
cover downloads have separate workers, so a slow ScreenScraper response does
not hold navigation behind it. The existing auto_download setting is honored.

Only a local-pack 404 enables the ScreenScraper fallback. The worker uses a
snapshot of the same `config.ini` ScreenScraper settings, system mapping,
media order and preferred region as the original monitor. It uses
`jeuRecherche.php` and accepts only an exact normalized title on the requested
system, rejecting ambiguous matches rather than displaying the first fuzzy
result. Searches are bounded to 256 KiB and media to 1 MiB, at most four media
attempts per game visit. Authentication/quota HTTP responses pause scraping
for five minutes. Successful images are requested at 172x242 as JPEG and saved
in `/library-cache-v1/`; later visits and reboots reuse them. Original monitor
artwork remains in its own cache. This is a name-based fallback, not the
original loaded-ROM CRC/hash workflow; some titles and regional variants will
not resolve. A later hash-based implementation would need a per-ROM identity
API, not the currently running game's status.

**ScreenScraper credentials:** custom builds do not contain the upstream
author's private developer credentials. Direct scraping needs your own
`ss_dev_user` and `ss_dev_pass` in addition to your member settings, configured
privately on the display's settings page. Do not put secrets in an issue, chat
or this repository. Without developer credentials, original cached images and
the installed MiSTer Artwork Pack still work. The UI now explains missing
configuration, HTTP failures and SD write failures. This build does not claim
that member credentials alone enable ScreenScraper.

Validation: 30 Python tests cover core choice, all seven aliases, preservation
of MGL launchers, refusal of unsupported RA overrides and the existing library
behavior. The native SD cache test covers bounds, isolation and write failures.
Firmware compilation validates both P4 revisions. Physical image display,
ScreenScraper responses with privately configured credentials, and RA gameplay
still require validation on the actual devices.

## Console logos and Nintendo 64 system ID

The native UI now shows the seven console logos on system cards, below game
covers and in the launch dialog. Separate 360x120 baseline JPEG data files are
shipped under `library/logos/`, served only through the allowlisted
`GET /library/logo?system=<id>` endpoint. Page responses include stable,
versioned `logo_id` values and local logo URLs. The display downloads each
system logo once into the same bounded 128-file/16 MiB cache as covers; six
games of one system reuse one logo. The existing cover worker handles logos
without ScreenScraper, with a 64 KiB transfer limit. Normal subfolders retain
their folder icons. Unknown systems, missing assets, missing SD and decode
failures fall back to the text label. Refresh renews visible logos and covers.

These separate art data files come from Rookervik's RetroPie Carbon theme;
original SVGs, complete upstream license text, attribution and transformation
notes are included beside the JPEGs. They are not embedded in the firmware.
`tools/build_library_logos.py` regenerates the JPEGs with CairoSVG and Pillow.

RA validation now queries canonical Remote catalog IDs: `Nintendo64` for N64,
`MasterSystem` for SMS and `TurboGrafx16` for TGFX16. These are distinct from
folder names and MGL filenames; the actual launcher remains `_RA_Cores/N64.mgl`.
The seven-system test checks this translation, including Nintendo64. The
HTTP integration test exercises all seven logos, aliases and traversal
rejection. A physical N64 launch still needs verification on the user's MiSTer.
