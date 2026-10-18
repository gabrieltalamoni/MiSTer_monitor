#!/bin/bash
# MiSTer Monitor library installer. SPDX-License-Identifier: AGPL-3.0-or-later
set -euo pipefail
cd -- "$(dirname -- "$0")"
SOURCE="$(pwd)/.config/mister_monitor"
TARGET=/media/fat/Scripts/.config/mister_monitor
if [ ! -f "$SOURCE/game_library.py" ] || [ ! -f "$SOURCE/library/index.html" ]; then
  echo "Pacote incompleto: extraia toda a pasta MiSTer/Scripts para o cartao."
  exit 1
fi
if [ ! -f /media/fat/Scripts/remote.sh ]; then
  echo "Instale e execute remote.sh (MiSTer Extensions) no menu Scripts primeiro."
  exit 1
fi
python3 - <<'PY'
from urllib.request import build_opener, ProxyHandler
try:
    build_opener(ProxyHandler({})).open('http://127.0.0.1:8182/api/systems',timeout=5).close()
except Exception:
    raise SystemExit('MiSTer Remote nao esta respondendo. Execute remote.sh e tente novamente.')
PY
mkdir -p "$TARGET"
# An overlay extraction can already have replaced the old server. Keep a
# separate copy of the current installation BEFORE extracting for rollback.
if [ "$SOURCE" != "$TARGET" ]; then
  BACKUP="${TARGET}/library-backup-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$BACKUP"
  [ ! -f "$TARGET/mister_status_server.py" ] || cp "$TARGET/mister_status_server.py" "$BACKUP/"
  cp "$SOURCE/mister_status_server.py" "$SOURCE/game_library.py" "$TARGET/"
  mkdir -p "$TARGET/library"
  cp "$SOURCE/library/index.html" "$SOURCE/library/app.js" "$TARGET/library/"
fi
python3 -m py_compile "$TARGET/game_library.py" "$TARGET/mister_status_server.py"
echo "Biblioteca instalada. Execute MiSTer_Monitor no menu Scripts para reiniciar."
echo "Depois abra http://<IP-do-MiSTer>:8081/library para conferir os jogos."
