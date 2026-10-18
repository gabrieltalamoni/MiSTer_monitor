# MiSTer Monitor — game library
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Paginated microSD library and a narrow, loopback-only MiSTer Remote bridge.

No game bytes are changed. Remote handles supported extensions, ZIP browsing
and core selection; no shell commands or guessed MGL slot numbers are used.
"""
import hashlib
import json
import os
import secrets
import threading
import time
from collections import OrderedDict
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler


DEFAULT_SYSTEMS = ('SNES', 'Genesis', 'SMS', 'TGFX16', 'NES', 'N64', 'PSX')
SYSTEM_ALIASES = {
    'snes': 'snes', 'supernintendo': 'snes', 'superfamicom': 'snes',
    'genesis': 'genesis', 'megadrive': 'genesis',
    'sms': 'sms', 'mastersystem': 'sms', 'segamastersystem': 'sms',
    'tgfx16': 'tgfx16', 'tg16': 'tgfx16', 'turbografx': 'tgfx16',
    'turbografx16': 'tgfx16', 'pcengine': 'tgfx16',
    'nes': 'nes', 'famicom': 'nes',
    'n64': 'n64', 'nintendo64': 'n64',
    'psx': 'psx', 'ps1': 'psx', 'playstation': 'psx',
}


class LibraryError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class RemoteClient:
    def __init__(self):
        # Ignore environment proxy settings and redirects: commands stay local.
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def call(self, endpoint, payload):
        req = Request('http://127.0.0.1:8182/api/' + endpoint,
                      data=json.dumps(payload).encode(),
                      headers={'Content-Type': 'application/json'}, method='POST')
        try:
            with self.opener.open(req, timeout=8) as response:
                raw = response.read(8 * 1024 * 1024 + 1)
                if len(raw) > 8 * 1024 * 1024:
                    raise LibraryError(502, 'Pasta muito grande. Divida os jogos em subpastas.')
                return json.loads(raw) if raw.strip() else {}
        except HTTPError as exc:
            message = exc.read(500).decode('utf-8', 'replace').strip()
            raise LibraryError(502, 'MiSTer Remote recusou a operação: ' + message)
        except (URLError, TimeoutError, OSError):
            raise LibraryError(503, 'Inicie o MiSTer Remote (remote.sh) em Scripts; porta 8182.')
        except (ValueError, TypeError):
            raise LibraryError(502, 'Resposta inválida do MiSTer Remote. Atualize remote.sh.')


class GameLibrary:
    def __init__(self, root='/media/fat', state_dir=None, remote=None, artwork=None,
                 systems=DEFAULT_SYSTEMS):
        self.root = os.path.abspath(root)
        self.games = os.path.join(self.root, 'games')
        self.arcade = os.path.join(self.root, '_Arcade')
        self.state_dir = state_dir or os.path.dirname(__file__)
        self.systems = None if systems is None else frozenset(
            self._system_key(name) for name in systems)
        self.favorites_file = os.path.join(self.state_dir, 'library_favorites.json')
        self.remote = remote or RemoteClient()
        self.artwork = artwork or (lambda item: '')
        self.token = secrets.token_hex(24)
        self.lock = threading.RLock()
        self.launch_lock = threading.Lock()
        self.last_launch = 0.0
        self.entries = OrderedDict()
        self.favorites = self._load_favorites()

    def _load_favorites(self):
        try:
            with open(self.favorites_file, encoding='utf-8') as handle:
                rows = json.load(handle)
            if not isinstance(rows, dict):
                return {}
            return {key: row for key, row in rows.items()
                    if isinstance(row, dict) and row.get('kind') == 'game'
                    and isinstance(row.get('path'), str)
                    and key == self._id(row['path']) and self.allowed(row['path'])}
        except (OSError, ValueError, TypeError):
            return {}

    @staticmethod
    def _id(path):
        return hashlib.sha256(path.encode('utf-8')).hexdigest()[:24]

    def allowed(self, path):
        if not isinstance(path, str) or not os.path.isabs(path) or len(path) > 2048:
            return False
        if any(ord(char) < 32 for char in path) or '..' in path.split('/'):
            return False
        # realpath also resolves the existing ancestor of ZIP virtual paths.
        resolved = os.path.realpath(path)
        for root in (self.games, self.arcade):
            try:
                if os.path.commonpath((resolved, root)) == root:
                    return True
            except ValueError:
                pass
        return False

    @staticmethod
    def _system_key(name):
        key = ''.join(char for char in name.casefold() if char.isalnum())
        return SYSTEM_ALIASES.get(key, key)

    def system_enabled(self, path):
        if self.systems is None:
            return True
        if path == self.arcade or path.startswith(self.arcade + '/'):
            return 'arcade' in self.systems
        folder = os.path.relpath(path, self.games).split(os.sep)[0]
        return self._system_key(folder) in self.systems

    def _normalise(self, item):
        if not isinstance(item, dict) or not self.allowed(item.get('path')):
            return None
        path = item['path']
        # Apply the selection before any recursive ROM/ZIP inspection.
        # Identity follows the games folder, not a possibly absent Remote ID.
        if not self.system_enabled(path):
            return None
        kind = item.get('type', '')
        if kind in ('folder', 'zip'):
            kind = 'folder'
        elif kind in ('game', 'mra', 'mgl'):
            kind = 'game'
        else:
            return None
        system = item.get('system') or {}
        if isinstance(system, dict):
            system = system.get('id', '')
        if not isinstance(system, str):
            system = ''
        if not system:
            relative = os.path.relpath(path, self.games).split(os.sep)
            system = 'Arcade' if path == self.arcade or path.startswith(self.arcade + '/') else relative[0]
        row = {'id': self._id(path), 'path': path, 'kind': kind,
               'name': str(item.get('name') or os.path.basename(path))[:180],
               'system': system[:80]}
        return row

    def _list_rows(self, folder):
        endpoint = 'menu/view' if folder.startswith(self.arcade) else 'games/view'
        raw = self.remote.call(endpoint, {'path': folder})
        if (not isinstance(raw, dict) or 'items' not in raw
                or (raw['items'] is not None and not isinstance(raw['items'], list))):
            raise LibraryError(502, 'Atualize o MiSTer Remote: listagem incompatível.')
        # Remote returns null rather than [] for some empty ZIP folders.
        return [row for item in (raw['items'] or []) if (row := self._normalise(item))]

    def _has_games(self, folder):
        """Find one Remote-recognised game, including subfolders and ZIPs.

        Do not infer presence from a system folder, cover, or ZIP filename.
        Empty physical directories need no HTTP call. Inspect fresh listings
        on every home request so adding/removing ROMs needs only Atualizar.
        """
        pending, visited = [folder], set()
        while pending:
            path = pending.pop()
            if not self.allowed(path):
                continue
            resolved = os.path.realpath(path)
            if resolved in visited:
                continue
            visited.add(resolved)
            if os.path.isdir(path):
                try:
                    with os.scandir(path) as entries:
                        if next(entries, None) is None:
                            continue
                except OSError:
                    raise LibraryError(500, 'Não foi possível verificar a pasta de jogos.')
            rows = self._list_rows(path)
            if any(row['kind'] == 'game' for row in rows):
                return True
            pending.extend(row['path'] for row in reversed(rows) if row['kind'] == 'folder')
        return False

    def page(self, folder='', page=1, per=6, query='', favorites=False):
        if not isinstance(folder, str) or not isinstance(query, str):
            raise LibraryError(400, 'Pasta ou busca inválida.')
        try:
            page, per = int(page), int(per)
        except (ValueError, TypeError):
            raise LibraryError(400, 'Página inválida.')
        if page < 1 or page > 1000000 or not 1 <= per <= 24 or len(query) > 120:
            raise LibraryError(400, 'Página ou busca fora dos limites.')
        if favorites:
            with self.lock:
                rows = [dict(row) for row in self.favorites.values()
                        if self.allowed(row['path']) and self.system_enabled(row['path'])]
            up = ''
        else:
            if folder and not self.allowed(folder):
                raise LibraryError(403, 'Somente jogos no microSD do MiSTer são permitidos.')
            if folder and not self.system_enabled(folder):
                raise LibraryError(403, 'Este sistema não está na seleção da biblioteca.')
            # Remote enumerates systems on all configured mounts. Filter before
            # sending them to the display: this screen is explicitly microSD.
            rows = self._list_rows(folder)
            if not folder and os.path.isdir(self.arcade):
                if not any(row['path'] == self.arcade for row in rows):
                    rows.insert(0, self._normalise({'path': self.arcade, 'name': 'Arcade', 'type': 'folder'}))
            if not folder:
                rows = [row for row in rows if row and
                        (row['kind'] == 'game' or self._has_games(row['path']))]
            up = os.path.dirname(folder) if folder else ''
            if up in (self.root, self.games) or not self.allowed(up):
                up = ''
        terms = query.casefold().split()
        rows = [row for row in rows if row and all(term in row['name'].casefold() for term in terms)]
        rows.sort(key=lambda row: (row['kind'] != 'folder', row['name'].casefold(), row['path']))
        total = len(rows)
        pages = max(1, (total + per - 1) // per)
        page = min(page, pages)
        selected = rows[(page - 1) * per:page * per]
        with self.lock:
            for row in selected:
                if row['kind'] == 'game':
                    self.entries[row['id']] = row
                    self.entries.move_to_end(row['id'])
                    while len(self.entries) > 4096:
                        self.entries.popitem(last=False)
                row['favorite'] = row['id'] in self.favorites
                row['artwork'] = '/library/artwork?id=' + row['id'] if row['kind'] == 'game' else ''
        return {'items': selected, 'page': page, 'pages': pages, 'total': total,
                'folder': folder, 'up': up, 'token': self.token,
                'source': 'microSD do MiSTer', 'search_scope': 'current_folder'}

    def entry(self, identity):
        if not isinstance(identity, str):
            raise LibraryError(400, 'Jogo inválido.')
        with self.lock:
            row = self.entries.get(identity) or self.favorites.get(identity)
            if row is not None:
                row = dict(row)
        if not row:
            raise LibraryError(404, 'Atualize a biblioteca e selecione o jogo novamente.')
        if not self.allowed(row['path']):
            raise LibraryError(403, 'Jogo fora do microSD permitido.')
        return row

    def set_favorite(self, identity, enabled):
        if type(enabled) is not bool:
            raise LibraryError(400, 'Favorito deve ser verdadeiro ou falso.')
        row = self.entry(identity)
        with self.lock:
            updated = dict(self.favorites)
            if enabled:
                if len(updated) >= 2000 and identity not in updated:
                    raise LibraryError(400, 'Limite de 2000 favoritos atingido.')
                updated[identity] = row
            else:
                updated.pop(identity, None)
            os.makedirs(self.state_dir, exist_ok=True)
            tmp = self.favorites_file + '.tmp'
            try:
                with open(tmp, 'w', encoding='utf-8') as handle:
                    json.dump(updated, handle, ensure_ascii=False)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp, self.favorites_file)
            except OSError:
                raise LibraryError(500, 'Não foi possível salvar os favoritos no cartão.')
            self.favorites = updated
        return {'favorite': enabled}

    def launch(self, identity, confirmed):
        if confirmed is not True:
            raise LibraryError(400, 'Confirme a troca de jogo antes de iniciar.')
        row = self.entry(identity)
        if not self.launch_lock.acquire(blocking=False):
            raise LibraryError(409, 'Já existe um lançamento em andamento.')
        try:
            if time.monotonic() - self.last_launch < 3:
                raise LibraryError(429, 'Aguarde alguns segundos antes de iniciar outro jogo.')
            # Remote selects the core, builds MGL and handles ZIP virtual paths.
            self.remote.call('games/launch', {'path': row['path']})
            self.last_launch = time.monotonic()
            return {'status': 'launch_requested', 'name': row['name']}
        finally:
            self.launch_lock.release()

    def respond(self, handler, status, body, mime='application/json; charset=utf-8'):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
        handler.send_response(status)
        handler.send_header('Content-Type', mime)
        handler.send_header('Content-Length', str(len(body)))
        handler.send_header('Cache-Control', 'no-store')
        handler.send_header('X-Content-Type-Options', 'nosniff')
        # Deliberately no wildcard CORS, including errors and tokens.
        handler.end_headers()
        handler.wfile.write(body)

    def handle(self, handler, method):
        parsed = urlparse(handler.path)
        if parsed.path != '/library' and not parsed.path.startswith('/library/'):
            return False
        try:
            query = parse_qs(parsed.query)
            get = lambda key, default='': query.get(key, [default])[0]
            if method == 'GET' and parsed.path in ('/library', '/library/', '/library/app.js'):
                name = 'app.js' if parsed.path.endswith('.js') else 'index.html'
                with open(os.path.join(os.path.dirname(__file__), 'library', name), 'rb') as handle:
                    data = handle.read()
                self.respond(handler, 200, data, 'application/javascript; charset=utf-8' if name.endswith('.js') else 'text/html; charset=utf-8')
            elif method == 'GET' and parsed.path == '/library/page':
                self.respond(handler, 200, self.page(get('folder'), get('page', '1'),
                             get('per', '6'), get('q'), get('favorites') == '1'))
            elif method == 'GET' and parsed.path == '/library/artwork':
                row = self.entry(get('id'))
                path = self.artwork(row)
                if not path or not os.path.isfile(path) or os.path.getsize(path) > 1024 * 1024:
                    raise LibraryError(404, 'Capa não disponível no pacote local.')
                with open(path, 'rb') as handle:
                    data = handle.read(1024 * 1024 + 1)
                if not data.startswith(b'\xff\xd8'):
                    raise LibraryError(404, 'Capa JPEG não disponível.')
                self.respond(handler, 200, data, 'image/jpeg')
            elif method == 'POST' and parsed.path in ('/library/launch', '/library/favorite'):
                self._mutate(handler, parsed.path)
            else:
                raise LibraryError(404, 'Rota não encontrada.')
        except LibraryError as exc:
            self.respond(handler, exc.status, {'error': exc.message})
        except (OSError, ValueError, TypeError, KeyError):
            self.respond(handler, 500, {'error': 'Não foi possível acessar a biblioteca.'})
        return True

    def _mutate(self, handler, path):
        origin = handler.headers.get('Origin')
        if origin and origin != 'http://' + handler.headers.get('Host', ''):
            raise LibraryError(403, 'Origem não permitida.')
        if handler.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json':
            raise LibraryError(415, 'Envie application/json.')
        try:
            length = int(handler.headers.get('Content-Length', '0'))
        except ValueError:
            raise LibraryError(400, 'Tamanho inválido.')
        if not 0 < length <= 4096:
            raise LibraryError(413, 'Requisição muito grande ou vazia.')
        try:
            data = json.loads(handler.rfile.read(length))
        except (ValueError, UnicodeError):
            raise LibraryError(400, 'JSON inválido.')
        if not isinstance(data, dict):
            raise LibraryError(400, 'Objeto JSON esperado.')
        token = data.get('token')
        if not isinstance(token, str) or not secrets.compare_digest(token, self.token):
            raise LibraryError(403, 'Atualize a biblioteca antes de continuar.')
        if path.endswith('/launch'):
            result = self.launch(data.get('id'), data.get('confirmed'))
        else:
            result = self.set_favorite(data.get('id'), data.get('enabled'))
        self.respond(handler, 200, result)
