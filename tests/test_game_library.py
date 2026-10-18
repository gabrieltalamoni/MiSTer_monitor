"""Behavior and HTTP integration checks, with a temporary microSD and Remote."""
import importlib.util
import io
import json
import os
import sys
import tempfile
import threading
import unittest
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

    def call(self, endpoint, payload):
        self.calls.append((endpoint, payload))
        if self.fail:
            raise LibraryError(503, 'Remote indisponível')
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


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name+'/sd'
        Path(self.root+'/games/SNES').mkdir(parents=True)
        self.remote = FakeRemote(self.root)
        self.lib = GameLibrary(self.root, self.tmp.name+'/state', self.remote)

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
