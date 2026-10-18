# Biblioteca de jogos — Guition 10,1 polegadas

Implementação experimental para o Guition JC8012P4A1C. Inclui uma interface
nativa de toque no display e uma interface de conferência no navegador.
Não foi validada em um Guition ou MiSTer físico durante o desenvolvimento.

## O que o usuário pode fazer

- Tocar em **Biblioteca**, no canto superior direito do monitor.
- Escolher um sistema do microSD do **MiSTer** e navegar por suas pastas.
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
- A montagem/linkedição não foi concluída: o executável assembler do ambiente
  falha por ausência de `/proc/self/exe`. **Não há `.bin` instalável nesta entrega.**
- O workflow de build está preparado para produzir os binários em GitHub Actions.
  Ele ainda não foi executado em um fork remoto.
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
