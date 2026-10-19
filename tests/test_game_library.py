"""Behavior and HTTP integration checks, with a temporary microSD and Remote."""
import importlib.util
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError

SOURCE = Path(__file__).resolve().parents[1] / 'MiSTer/Scripts/.config/mister_monitor'
sys.path.insert(0, str(SOURCE))
from game_library import GameLibrary, LibraryError, RemoteClient


class FakeRemote:
    def __init__(self, root):
        self.root, self.calls, self.fail = root, [], False

    def call(self, endpoint, payload=None):
        self.calls.append((endpoint, payload))
        if self.fail:
            raise LibraryError(503, 'Remote indisponível')
        if endpoint.endswith('/rbfs'):
            return self.rbfs
        if endpoint == 'games/launch':
            return {}
        folder = payload['path']
        if not folder:
            return {'items': [
                {'path': self.root+'/games/SNES', 'type':'folder', 'name':'SNES'},
                {'path': '/media/usb0/games/NES', 'type':'folder', 'name':'USB'},
                {'path': self.root+'/games-escape/NES', 'type':'folder', 'name':'Escape'}]}
        return {'items': [
            {'path': folder+'/'+name+'.sfc', 'name':name, 'type':'game', 'system':{'id':'SNES'}}
            for name in ['Zelda (USA)', 'Contra III', 'Super Mario World', 'F-Zero',
                         'Donkey Kong', 'Mega Man X', 'Yoshi', 'Ação & "aventura"']]}


class TreeRemote:
    """Explicit Remote listings, including virtual ZIP directories."""
    def __init__(self, views):
        self.views, self.calls = views, []

    def call(self, endpoint, payload):
        self.calls.append((endpoint, payload))
        result = self.views[payload['path']]
        if isinstance(result, Exception):
            raise result
        return result


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name+'/sd'
        Path(self.root+'/games/SNES').mkdir(parents=True)
        Path(self.root+'/games/SNES/Super Mario World.sfc').touch()
        self.remote = FakeRemote(self.root)
        self.lib = GameLibrary(self.root, self.tmp.name+'/state', self.remote, systems=None)

    def tearDown(self):
        self.tmp.cleanup()

    def games(self, **kwargs):
        return self.lib.page(self.root+'/games/SNES', **kwargs)

    def test_only_microsd_roots_and_bounded_pages(self):
        home = self.lib.page()
        self.assertEqual([x['name'] for x in home['items']], ['SNES'])
        first, second = self.games(), self.games(page=2)
        self.assertEqual((first['total'], first['pages']), (8,2))
        self.assertEqual((len(first['items']), len(second['items'])), (6,2))
        self.assertFalse({x['id'] for x in first['items']} & {x['id'] for x in second['items']})
        self.assertEqual(self.games(query='super mario')['items'][0]['name'], 'Super Mario World')

    def tree(self, listings):
        views = {folder: {'items': items} for folder, items in listings.items()}
        self.remote = TreeRemote(views)
        self.lib = GameLibrary(self.root, self.tmp.name+'/state', self.remote, systems=None)

    @staticmethod
    def row(path, kind='folder'):
        return {'path': str(path), 'type': kind, 'name': Path(path).name}

    def test_systems_require_games_including_nested_zip_and_arcade(self):
        games = Path(self.root)/'games'
        empty, media, nested, zipped = [games/name for name in ('Empty', 'MediaOnly', 'NES', 'Genesis')]
        arcade = Path(self.root)/'_Arcade'
        for folder in (empty, media, nested/'USA', zipped, arcade/'Classics'):
            folder.mkdir(parents=True)
        (media/'cover.jpg').touch()
        (nested/'USA'/'Mario.nes').touch()
        (zipped/'Batman.zip').touch()
        (arcade/'Classics'/'1942.mra').touch()
        self.tree({
            '': [self.row(p) for p in (empty, media, nested, zipped, games/'SNES')],
            str(media): [],  # Remote excludes artwork, configuration and text files.
            str(games/'SNES'): [self.row(games/'SNES'/'Mario.sfc', 'game')],
            str(nested): [self.row(nested/'USA')],
            str(nested/'USA'): [self.row(nested/'USA'/'Mario.nes', 'game')],
            str(zipped): [self.row(zipped/'Batman.zip', 'zip')],
            str(zipped/'Batman.zip'): [self.row(zipped/'Batman.zip'/'Batman.md', 'game')],
            str(arcade): [self.row(arcade/'Classics')],
            str(arcade/'Classics'): [self.row(arcade/'Classics'/'1942.mra', 'mra')],
        })
        home = self.lib.page(per=24)
        self.assertEqual([row['name'] for row in home['items']], ['Arcade', 'Genesis', 'NES', 'SNES'])
        self.assertEqual((home['total'], home['pages']), (4, 1))
        self.assertNotIn(('games/view', {'path': str(empty)}), self.remote.calls)
        self.assertIn(('menu/view', {'path': str(arcade/'Classics')}), self.remote.calls)
        # Ordinary folder navigation still shows its folders and ZIPs.
        self.assertEqual(self.lib.page(str(zipped))['items'][0]['kind'], 'folder')

    def test_home_refresh_tracks_added_and_removed_games(self):
        folder = Path(self.root)/'games/SNES'
        rom = folder/'Super Mario World.sfc'
        self.tree({'': [self.row(folder)], str(folder): []})
        self.assertEqual(self.lib.page()['total'], 0)
        self.remote.views[str(folder)]['items'] = [self.row(rom, 'game')]
        self.assertEqual(self.lib.page(refresh=True)['total'], 1)
        rom.unlink()
        self.remote.views[str(folder)]['items'] = []
        self.assertEqual(self.lib.page(refresh=True)['total'], 0)

    def test_cached_home_and_pagination_avoid_remote_queries(self):
        self.lib.page()
        calls = len(self.remote.calls)
        self.lib.page(page=2, per=1)
        self.lib.page(query='snes')
        self.assertEqual(len(self.remote.calls), calls)
        first = self.games()
        self.games(page=2)
        self.games(query='super mario')
        self.assertEqual(len(self.remote.calls), calls)
        self.assertEqual(first['total'], 8)

    def test_cache_expires_and_explicit_refresh_sees_changes(self):
        folder = self.root+'/games/SNES'
        self.tree({'': [self.row(folder)], folder: [self.row(folder+'/Mario.sfc', 'game')]})
        with patch('game_library.time.monotonic', return_value=100):
            self.assertEqual(self.lib.page()['total'], 1)
        self.remote.views[folder]['items'] = []
        with patch('game_library.time.monotonic', return_value=120):
            self.assertEqual(self.lib.page()['total'], 1)
        with patch('game_library.time.monotonic', return_value=161):
            self.assertEqual(self.lib.page()['total'], 0)
            self.remote.views[folder]['items'] = [self.row(folder+'/Mario.sfc', 'game')]
            self.assertEqual(self.lib.page(refresh=True)['total'], 1)

    def test_cached_rows_keep_favorite_flags_fresh(self):
        item = self.games()['items'][0]
        self.lib.set_favorite(item['id'], True)
        self.assertTrue(self.games()['items'][0]['favorite'])
        self.lib.set_favorite(item['id'], False)
        self.assertFalse(self.games()['items'][0]['favorite'])

    def test_concurrent_pages_share_one_remote_listing(self):
        barrier = threading.Barrier(4)
        results = []
        def browse():
            barrier.wait()
            results.append(self.games()['total'])
        threads = [threading.Thread(target=browse) for _ in range(4)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=5)
        self.assertEqual(results, [8]*4)
        self.assertEqual(len(self.remote.calls), 1)

    def test_cache_budget_and_lru_eviction(self):
        self.lib.cache_budget = 7000
        for number in range(12):
            self.lib.page(self.root+'/games/SNES/folder'+str(number))
        self.assertLessEqual(self.lib.list_cache_bytes, self.lib.cache_budget)
        calls = len(self.remote.calls)
        self.lib.page(self.root+'/games/SNES/folder0')
        self.assertEqual(len(self.remote.calls), calls+1)

    def test_http_refresh_flag_invalidates_cached_catalogue(self):
        folder = self.root+'/games/SNES'
        self.tree({'': [self.row(folder)], folder: [self.row(folder+'/Mario.sfc', 'game')]})
        lib = self.lib
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self): lib.handle(self, 'GET')
            def log_message(self, *args): pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        opener = build_opener(ProxyHandler({}))
        base = 'http://127.0.0.1:'+str(server.server_port)+'/library/page'
        try:
            with opener.open(base) as response:
                self.assertEqual(json.load(response)['total'], 1)
            self.remote.views[folder]['items'] = []
            with opener.open(base) as response:
                self.assertEqual(json.load(response)['total'], 1)
            with opener.open(base+'?refresh=1') as response:
                self.assertEqual(json.load(response)['total'], 0)
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_empty_zip_and_empty_arcade_are_hidden(self):
        folder = Path(self.root)/'games/SNES'
        (folder/'Super Mario World.sfc').unlink()
        (folder/'Empty.zip').touch()
        arcade = Path(self.root)/'_Arcade'
        arcade.mkdir()
        self.tree({'': [self.row(folder), self.row(arcade)],
                   str(folder): [self.row(folder/'Empty.zip', 'zip')]})
        self.remote.views[str(folder/'Empty.zip')] = {'items': None}
        self.assertEqual(self.lib.page()['total'], 0)
        self.assertEqual(self.lib.page(str(folder/'Empty.zip'))['items'], [])

    def test_system_scan_rejects_escape_and_stops_symlink_cycles(self):
        folder = Path(self.root)/'games/Cycle'
        folder.mkdir()
        (folder/'again').symlink_to(folder, target_is_directory=True)
        outside = Path(self.tmp.name)/'outside'
        outside.mkdir()
        (outside/'Secret.sfc').touch()
        (folder/'external').symlink_to(outside, target_is_directory=True)
        self.tree({'': [self.row(folder)], str(folder): [self.row(folder/'again'), self.row(folder/'external')]})
        self.assertEqual(self.lib.page()['total'], 0)
        self.assertEqual(len(self.remote.calls), 2)

    def test_system_filter_runs_before_pagination(self):
        games = Path(self.root)/'games'
        empty = [games/('Empty'+str(i)) for i in range(20)]
        for folder in empty:
            folder.mkdir()
        nes = games/'NES'
        nes.mkdir()
        (nes/'Mario.nes').touch()
        snes = games/'SNES'
        self.tree({'': [self.row(p) for p in (*empty, snes, nes)],
                   str(nes): [self.row(nes/'Mario.nes', 'game')],
                   str(snes): [self.row(snes/'Mario.sfc', 'game')]})
        first, second = self.lib.page(per=1), self.lib.page(per=1, page=2)
        self.assertEqual((first['total'], first['pages']), (2, 2))
        self.assertEqual(first['items'][0]['name'], 'NES')
        self.assertEqual(second['items'][0]['name'], 'SNES')
        self.assertEqual(self.lib.page(query='snes')['total'], 1)

    def test_system_scan_errors_are_not_reported_as_empty(self):
        folder = Path(self.root)/'games/SNES'
        self.tree({'': [self.row(folder)]})
        for result in (LibraryError(503, 'Remote indisponível'), {'items': 'invalid'}, {}):
            self.remote.views[str(folder)] = result
            with self.subTest(result=result), self.assertRaises(LibraryError):
                self.lib.page()

    def test_system_scan_stops_at_first_game(self):
        folder = Path(self.root)/'games/SNES'
        self.tree({'': [self.row(folder)], str(folder): [
            self.row(folder/'Unreadable'), self.row(folder/'Mario.sfc', 'game')]})
        self.assertEqual(self.lib.page()['total'], 1)
        self.assertEqual(len(self.remote.calls), 2)

    def test_default_selection_skips_other_systems_before_scanning(self):
        games = Path(self.root)/'games'
        selected = ('SNES', 'MegaDrive', 'MasterSystem', 'TGFX16', 'NES', 'N64', 'PSX')
        excluded = ('Amiga', 'GBA', 'MegaCD', 'TGFX16-CD', 'SuperGrafx', 'Atari2600')
        folders = [games/name for name in (*selected, *excluded)]
        for folder in folders:
            folder.mkdir(exist_ok=True)
            (folder/'ROM.bin').touch()
        arcade = Path(self.root)/'_Arcade'
        arcade.mkdir()
        (arcade/'1942.mra').touch()
        # Missing views for excluded systems make any unnecessary scan fail.
        self.tree({'': [self.row(p) for p in folders], **{
            str(games/name): [self.row(games/name/'ROM.bin', 'game')]
            for name in selected}})
        self.lib = GameLibrary(self.root, self.tmp.name+'/state', self.remote)
        home = self.lib.page(per=24)
        self.assertEqual({row['name'] for row in home['items']}, set(selected))
        self.assertEqual(home['total'], 7)
        self.assertEqual(len(self.remote.calls), 8)  # Root + seven selected systems.
        for name in excluded:
            with self.assertRaises(LibraryError) as err:
                self.lib.page(str(games/name))
            self.assertEqual(err.exception.status, 403)

    def test_selected_system_aliases_and_case(self):
        lib = GameLibrary(self.root, self.tmp.name+'/state', self.remote)
        for name in ('SNES', 'snes', 'Super Nintendo', 'MegaDrive', 'MEGADRIVE',
                     'Genesis', 'SMS', 'Master System', 'TurboGrafx', 'TurboGrafx-16',
                     'TG16', 'TGFX16', 'PC Engine', 'NES', 'N64', 'Nintendo 64',
                     'PSX', 'PS1', 'PlayStation'):
            with self.subTest(name=name):
                self.assertTrue(lib.system_enabled(self.root+'/games/'+name+'/ROM.zip/Game.bin'))
        for name in ('TGFX16-CD', 'MegaCD', 'SuperGrafx', 'FDS', 'GBA'):
            self.assertFalse(lib.system_enabled(self.root+'/games/'+name+'/ROM.bin'))
        self.assertFalse(lib.system_enabled(self.root+'/_Arcade/1942.mra'))

    def test_selection_keeps_only_populated_systems(self):
        games = Path(self.root)/'games'
        (games/'NES').mkdir()
        self.tree({'': [self.row(games/'SNES'), self.row(games/'NES')],
                   str(games/'SNES'): [self.row(games/'SNES'/'Mario.sfc', 'game')]})
        self.lib = GameLibrary(self.root, self.tmp.name+'/state', self.remote)
        self.assertEqual([row['name'] for row in self.lib.page()['items']], ['SNES'])

    def test_hidden_system_favorites_are_preserved_but_not_displayed(self):
        games = Path(self.root)/'games'
        self.tree({str(games/'GBA'): [self.row(games/'GBA'/'Metroid.gba', 'game')]})
        item = self.lib.page(str(games/'GBA'))['items'][0]
        self.lib.set_favorite(item['id'], True)
        selected = GameLibrary(self.root, self.tmp.name+'/state', self.remote)
        self.assertEqual(selected.page(favorites=True)['total'], 0)
        all_systems = GameLibrary(self.root, self.tmp.name+'/state', self.remote, systems=None)
        self.assertEqual(all_systems.page(favorites=True)['items'][0]['id'], item['id'])

    def test_traversal_symlink_and_prefix_sibling_rejected(self):
        outside = Path(self.tmp.name)/'outside'; outside.mkdir()
        Path(self.root+'/games/SNES/link').symlink_to(outside, target_is_directory=True)
        for path in [self.root+'/games-escape/rom.nes', self.root+'/games/../../secret',
                     self.root+'/games/SNES/link/rom.nes', '/etc/passwd', self.root+'/games/a\n.nes']:
            with self.subTest(path=path):
                self.assertFalse(self.lib.allowed(path))
                with self.assertRaises(LibraryError): self.lib.page(path)

    def test_zip_virtual_paths_stay_in_games_root(self):
        path = self.root+'/games/SNES/Collection.zip/Super Mario World.sfc'
        self.assertTrue(self.lib.allowed(path))
        self.assertFalse(self.lib.allowed(self.root+'/games/SNES/a.zip/../../../linux/config'))

    def test_launch_requires_confirmed_registered_identity(self):
        item = self.games()['items'][0]
        with self.assertRaises(LibraryError): self.lib.launch(item['id'], False)
        with self.assertRaises(LibraryError): self.lib.launch('unknown', True)
        self.assertEqual(self.lib.launch(item['id'], True)['status'], 'launch_requested')
        self.assertEqual(self.remote.calls[-1], ('games/launch', {'path':item['path']}))
        with self.assertRaises(LibraryError) as err: self.lib.launch(item['id'], True)
        self.assertEqual(err.exception.status, 429)

    def test_favorites_survive_restart_and_can_be_removed(self):
        item = self.games()['items'][0]
        self.lib.set_favorite(item['id'], True)
        restarted = GameLibrary(self.root, self.tmp.name+'/state', self.remote)
        saved = restarted.page(favorites=True)['items']
        self.assertEqual(saved[0]['id'], item['id'])
        self.assertTrue(saved[0]['favorite'])
        restarted.set_favorite(item['id'], False)
        self.assertEqual(restarted.page(favorites=True)['total'], 0)
        self.assertFalse(Path(restarted.favorites_file+'.tmp').exists())

    def test_installed_ra_launchers_preserve_mgl_for_all_seven_systems(self):
        for system, name in [('SNES', 'SNES'), ('Genesis', 'MegaDrive'),
                             ('SMS', 'SMS'), ('TGFX16', 'TurboGrafx16'),
                             ('NES', 'NES'), ('N64', 'N64'), ('PSX', 'PSX')]:
            with self.subTest(system=system):
                launcher = '_RA_Cores/' + name + '.mgl'
                path = Path(self.root)/launcher
                path.parent.mkdir(exist_ok=True)
                path.write_text('<mistergamedescription/>')
                self.remote.rbfs = [{'rbf': launcher, 'setname': 'RA_' + name}]
                item = dict(self.games()['items'][0], system=system)
                self.lib.entries[item['id']] = item
                self.lib.last_launch = 0
                self.lib.launch(item['id'], True)
                remote_id = {'N64': 'Nintendo64', 'SMS': 'MasterSystem',
                             'TGFX16': 'TurboGrafx16'}.get(system, system)
                self.assertEqual(self.remote.calls[-2], ('systems/' + remote_id + '/rbfs', None))
                self.assertEqual(self.remote.calls[-1], ('games/launch',
                                 {'path': item['path'], 'rbf': launcher}))

    def test_ra_not_advertised_never_silently_launches_standard(self):
        folder = Path(self.root)/'_RA_Cores'
        folder.mkdir()
        (folder/'SNES.mgl').touch()
        self.remote.rbfs = [{'rbf': '_Console/SNES', 'setname': ''}]
        item = self.games()['items'][0]
        with self.assertRaises(LibraryError) as err:
            self.lib.launch(item['id'], True)
        self.assertEqual(err.exception.status, 409)
        self.assertFalse(any(endpoint == 'games/launch' for endpoint, _ in self.remote.calls))

    def test_ra_requires_setname_and_survives_remote_failure_without_launch(self):
        folder = Path(self.root)/'_RA_Cores'
        folder.mkdir()
        (folder/'SNES.mgl').touch()
        item = self.games()['items'][0]
        for advertised in (None, {}, [{'rbf': '_RA_Cores/SNES.mgl', 'setname': ''}]):
            self.remote.rbfs = advertised
            with self.assertRaises(LibraryError):
                self.lib.launch(item['id'], True)
        self.remote.fail = True
        with self.assertRaises(LibraryError):
            self.lib.launch(item['id'], True)
        self.assertFalse(any(endpoint == 'games/launch' for endpoint, _ in self.remote.calls))

    def test_remote_get_request_does_not_post_empty_json(self):
        client = RemoteClient()
        response = io.BytesIO(b'[]')
        with patch.object(client.opener, 'open', return_value=response) as opened:
            self.assertEqual(client.call('systems/NES/rbfs'), [])
        request = opened.call_args.args[0]
        self.assertEqual(request.get_method(), 'GET')
        self.assertIsNone(request.data)
        self.assertEqual(request.full_url, 'http://127.0.0.1:8182/api/systems/NES/rbfs')
    def test_large_folder_first_page_remains_launchable(self):
        self.remote.call = lambda endpoint, payload: {'items':[
            {'name':str(i).zfill(5),'path':self.root+'/games/SNES/'+str(i)+'.sfc','type':'game'}
            for i in range(6000)]} if endpoint != 'games/launch' else {}
        item = self.games()['items'][0]
        self.assertEqual(self.lib.entry(item['id'])['path'], item['path'])
        self.assertLessEqual(len(self.lib.entries), 4096)

    def test_bad_pagination_and_remote_failure_are_explicit(self):
        for args in [{'page':0},{'per':10000},{'page':'x'},{'query':'x'*121}]:
            with self.assertRaises(LibraryError): self.games(**args)
        self.remote.fail = True
        with self.assertRaises(LibraryError) as err: self.games()
        self.assertEqual(err.exception.status, 503)

    def test_http_token_origin_json_and_actual_launch(self):
        lib = self.lib
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self): lib.handle(self, 'GET')
            def do_POST(self): lib.handle(self, 'POST')
            def log_message(self, *args): pass
        server = ThreadingHTTPServer(('127.0.0.1',0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        opener = build_opener(ProxyHandler({}))
        base = 'http://127.0.0.1:'+str(server.server_port)
        try:
            with opener.open(base+'/library/page') as response:
                self.assertIsNone(response.headers.get('Access-Control-Allow-Origin'))
            with opener.open(base+'/library') as response:
                self.assertIn(b'Sua pr',response.read())
            item = self.games()['items'][0]
            for data, origin, status in [
                ({'id':item['id'],'confirmed':True},base,403),
                ({'id':item['id'],'confirmed':True,'token':lib.token},'http://evil.example',403),
                ([],base,400),
                ({'id':item['id'],'confirmed':False,'token':lib.token},base,400)]:
                req=Request(base+'/library/launch',data=json.dumps(data).encode(),
                    headers={'Content-Type':'application/json','Origin':origin})
                with self.assertRaises(HTTPError) as err: opener.open(req)
                self.assertEqual(err.exception.code,status)
            req=Request(base+'/library/launch',data=json.dumps({'id':item['id'],'confirmed':True,'token':lib.token}).encode(),
                headers={'Content-Type':'application/json','Origin':base})
            with opener.open(req) as response:
                self.assertEqual(json.load(response)['status'],'launch_requested')
        finally:
            server.shutdown();server.server_close();thread.join()

    def test_logo_http_allowlist_aliases_and_page_metadata(self):
        lib = self.lib
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self): lib.handle(self, 'GET')
            def log_message(self, *args): pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        opener = build_opener(ProxyHandler({}))
        base = 'http://127.0.0.1:' + str(server.server_port)
        try:
            for system in ['SNES', 'MegaDrive', 'MasterSystem', 'TG16', 'NES',
                           'N64', 'Nintendo64', 'PSX']:
                with self.subTest(system=system):
                    with opener.open(base + '/library/logo?system=' + system) as response:
                        data = response.read()
                        self.assertEqual(response.headers['Content-Type'], 'image/jpeg')
                        self.assertTrue(data.startswith(bytes([255, 216])))
                        self.assertLessEqual(len(data), 65536)
                        self.assertIsNone(response.headers.get('Access-Control-Allow-Origin'))
            for system in ['Arcade', '../../config.ini', 'unknown']:
                with self.assertRaises(HTTPError) as err:
                    opener.open(base + '/library/logo?system=' + system)
                self.assertEqual(err.exception.code, 404)
            item = self.games()['items'][0]
            self.assertEqual(item['logo'], '/library/logo?system=snes')
            self.assertEqual(item['logo_id'], lib._id('system-logo-v1:snes'))
            self.assertNotEqual(item['id'], item['logo_id'])
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_integrated_status_handler_exposes_library(self):
        spec=importlib.util.spec_from_file_location('status_server_for_test',SOURCE/'mister_status_server.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        self.assertIsNotNone(module._game_library)
        module._game_library=self.lib
        # Exercise the actual cover resolver with an installed pack and its
        # representative-name index, independently of the active game's state.
        artwork_dir=Path(self.root)/'docs/SNES/Artwork'
        artwork_dir.mkdir(parents=True)
        cover=artwork_dir/'representative.jpg'
        cover.write_bytes((SOURCE.parents[3]/'SD_card_content/Guition/cores/menu.jpg').read_bytes())
        (artwork_dir/'index.tsv').write_text('Super Mario World\t\t\trepresentative\n')
        module._PACK_MOUNTS=[self.root]
        self.lib.artwork=module._library_artwork
        mario=self.games(query='super mario')['items'][0]
        self.assertEqual(module._library_artwork(mario),str(cover))
        server=ThreadingHTTPServer(('127.0.0.1',0),module.MiSTerStatusHandler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            opener=build_opener(ProxyHandler({}))
            with opener.open('http://127.0.0.1:'+str(server.server_port)+'/library/page') as response:
                self.assertEqual(json.load(response)['total'],1)
            with opener.open('http://127.0.0.1:'+str(server.server_port)+'/status/version') as response:
                self.assertEqual(json.load(response)['server_version'],'2.12.0')
            with opener.open('http://127.0.0.1:'+str(server.server_port)+'/library/artwork?id='+mario['id']) as response:
                self.assertEqual(response.headers['Content-Type'],'image/jpeg')
                self.assertEqual(response.read(),cover.read_bytes())
        finally:
            server.shutdown();server.server_close();thread.join()


if __name__ == '__main__':
    unittest.main()
