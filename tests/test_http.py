from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from bsc import providers
from bsc.keystore import Keystore
from bsc.server import AppServer, serve
from bsc.workspace import Workspace
from bsc.security import InputError

ROOT = Path(__file__).resolve().parent.parent
PLAN = json.loads((ROOT/'examples/inventory-plan.json').read_text())

class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory();cls.secrets=tempfile.TemporaryDirectory()
        cls.ws=Workspace(Path(cls.tmp.name), Keystore(Path(cls.secrets.name)))
        cls.server=AppServer(('127.0.0.1',0),cls.ws)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.url=cls.server.origin
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join();cls.secrets.cleanup();cls.tmp.cleanup()
    def request(self,path,data=None,headers=None):
        h={'X-BSC-Token':self.server.token}
        if data is not None: h['Content-Type']='application/json'
        h.update(headers or {})
        req=urllib.request.Request(self.url+path,data=None if data is None else json.dumps(data).encode(),headers=h)
        return urllib.request.urlopen(req,timeout=30)
    def test_static_ui(self):
        with self.request('/') as r:
            self.assertIn(b'Bot Skill Creator',r.read());self.assertIn('frame-ancestors',r.headers['Content-Security-Policy'])
    def test_bootstrap(self):
        with self.request('/api/bootstrap') as r:self.assertIn('token',json.load(r))
    def test_unknown_route(self):
        with self.assertRaises(urllib.error.HTTPError) as exc:self.request('/missing')
        self.assertEqual(exc.exception.code,404)
    def test_cross_origin_rejected(self):
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/projects',{}, {'Origin':'https://evil.example'})
    def test_bad_host_rejected(self):
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/bootstrap',headers={'Host':'evil.example'})
    def test_write_without_token_rejected(self):
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/projects',{}, {'X-BSC-Token':''})
    def test_private_get_without_token_rejected(self):
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/project?id=abc',headers={'X-BSC-Token':''})
    def test_local_models_route_stays_on_loopback(self):
        with self.assertRaises(urllib.error.HTTPError) as exc:
            self.request('/api/local-models', headers={'X-BSC-Token':''})
        self.assertEqual(exc.exception.code, 403)
        with self.request('/api/local-models') as response:
            data = json.load(response)
        self.assertIsInstance(data['models'], list)
        for model in data['models']:
            self.assertTrue(model['local'])
            self.assertTrue(model['base_url'].startswith('http://127.0.0.1:'))
            self.assertFalse(model['json_mode'])
            self.assertEqual(model['token_field'], 'max_tokens')
            self.assertNotIn('api_key', model)
            self.assertIn(':11434', model['base_url'])
    def test_save_key_is_sealed_and_not_echoed(self):
        secret='route-test-key-not-real'
        with self.request('/api/provider/key', {'provider':'openrouter','api_key':secret}) as response:
            data=json.load(response)
        self.assertTrue(data['saved'])
        self.assertEqual(data['confirmation'], 'Saved for the next session.')
        self.assertNotIn(secret, json.dumps(data))
        blob=(Path(self.secrets.name)/'openrouter.key').read_bytes()
        self.assertNotIn(secret.encode(), blob)
        self.assertEqual(self.ws.keystore.load('openrouter'), secret)
        with self.request('/api/bootstrap') as response:
            status=json.load(response)
        self.assertIn('openrouter', status['saved_keys'])
        self.assertNotIn(secret, json.dumps(status))
        with self.assertRaises(urllib.error.HTTPError):
            self.request('/api/provider/key', {'provider':'local','api_key':secret})
        with self.assertRaises(urllib.error.HTTPError):
            self.request('/api/provider/key', {'provider':'openai','api_key':'   '})
    def test_draft_phase_says_analyzing_harness(self):
        with self.request('/api/projects', {}) as response:
            project = json.load(response)
        self.ws.set_phase(project['id'], 'analyzing')
        try:
            with self.request('/api/draft-phase?id=' + project['id']) as response:
                phase = json.load(response)
            self.assertEqual(phase['label'], 'Analyzing harness')
        finally:
            self.ws.clear_phase(project['id'])
        script = (ROOT / 'bsc' / 'web' / 'app.js').read_text(encoding='utf-8')
        self.assertIn('Analyzing harness', script)
        self.assertIn('/api/draft-phase', script)
    def test_tool_generation_route_is_gone(self):
        with self.request('/api/projects', {}) as response:
            project = json.load(response)
        with self.request('/api/chat', {'id': project['id'], 'message': 'Build a read-only inventory brief.', 'tool_generation': True}) as response:
            project = json.load(response)
        self.assertFalse(project['tool_generation'])
        self.assertNotIn('tools/run_tool.py', project['files'])
        with self.assertRaises(urllib.error.HTTPError) as missing:
            self.request('/api/tool-generation', {'id': project['id'], 'enabled': True})
        self.assertEqual(missing.exception.code, 404)
    def test_create_chat_export(self):
        with self.request('/api/projects',{}) as r:p=json.load(r)
        with self.request('/api/chat',{'id':p['id'],'message':'Build a read-only inventory brief.'}) as r:p=json.load(r)
        self.assertTrue(p['validation']['ok'])
        with self.request('/api/export',{'id':p['id'],'fingerprint':p['export_fingerprint']}) as r:
            self.assertEqual(r.headers['Content-Type'],'application/zip');self.assertTrue(r.read().startswith(b'PK'))
    def test_public_bind_refused(self):
        with self.assertRaises(ValueError):AppServer(('0.0.0.0',0),self.ws)
    def test_presence_is_idle_until_a_page_launch(self):
        with self.request('/api/bootstrap') as response:
            self.assertFalse(json.load(response)['until_close'])
        with self.request('/api/presence', {'client': 'pagefallback01'}) as response:
            body = json.load(response)
        self.assertFalse(body['until_close'])
        self.assertTrue(self.thread.is_alive())

def _wait_until(predicate, timeout):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return False

def _port_open(origin):
    try:
        with urllib.request.urlopen(origin + '/', timeout=0.5) as response:
            return response.status == 200
    except Exception:
        return False

class PageLifetimeTests(unittest.TestCase):
    def _serve(self, directory, **kwargs):
        holder = {}
        started = threading.Event()
        def run():
            original = AppServer.__init__
            def wrapped(self, addr, workspace):
                AppServer.__init__ = original
                original(self, addr, workspace)
                holder['server'] = self
                started.set()
            AppServer.__init__ = wrapped
            try:
                serve(directory, 0, quiet=True, **kwargs)
            finally:
                AppServer.__init__ = original
                started.set()
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.assertTrue(started.wait(3))
        self.assertIn('server', holder)
        return holder['server'], thread

    def _beat(self, server, client, token=True):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['X-BSC-Token'] = server.token
        request = urllib.request.Request(server.origin + '/api/presence', data=json.dumps({'client': client}).encode(), headers=headers)
        return urllib.request.urlopen(request, timeout=2)

    def test_page_keeps_the_server_until_it_goes_quiet(self):
        with tempfile.TemporaryDirectory() as tmp:
            server, thread = self._serve(Path(tmp), until_close=True, idle_seconds=1.5, startup_grace=5)
            with self._beat(server, 'studio-page-a') as response:
                self.assertTrue(json.load(response)['until_close'])
            self.assertTrue(_port_open(server.origin))
            time.sleep(0.4)
            self.assertTrue(_port_open(server.origin))
            self.assertTrue(_wait_until(lambda: not _port_open(server.origin), 4))
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive())

    def test_two_pages_hold_the_server_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            server, thread = self._serve(Path(tmp), until_close=True, idle_seconds=2.5, startup_grace=5)
            self._beat(server, 'studio-page-a').close()
            self._beat(server, 'studio-page-b').close()
            time.sleep(1.0)
            self._beat(server, 'studio-page-b').close()
            self.assertTrue(_port_open(server.origin))
            self.assertTrue(_wait_until(lambda: not _port_open(server.origin), 5))
            thread.join(timeout=3)

    def test_unused_launch_stops_without_a_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            server, thread = self._serve(Path(tmp), until_close=True, idle_seconds=2, startup_grace=0.6)
            self.assertTrue(_wait_until(lambda: not _port_open(server.origin), 3))
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive())

    def test_presence_requires_the_session_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            server, thread = self._serve(Path(tmp), until_close=True, idle_seconds=3, startup_grace=5)
            try:
                with self.assertRaises(urllib.error.HTTPError) as blocked:
                    self._beat(server, 'studio-page-a', token=False)
                self.assertEqual(blocked.exception.code, 400)
                self.assertIn(b'Missing local session token', blocked.exception.read())
                with self.assertRaises(urllib.error.HTTPError) as bad:
                    self._beat(server, 'no', token=True)
                self.assertEqual(bad.exception.code, 400)
            finally:
                server.shutdown()
                thread.join(timeout=3)

    def test_open_reuses_a_studio_that_is_already_listening(self):
        from bsc import server as server_mod
        opened = []
        original = server_mod.webbrowser.open
        server_mod.webbrowser.open = opened.append
        try:
            with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other:
                server, thread = self._serve(Path(tmp), until_close=False)
                try:
                    port = int(server.origin.rsplit(':', 1)[1])
                    serve(Path(other), port, open_browser=True, quiet=True)
                    self.assertEqual(opened, [server.origin + '/'])
                    self.assertTrue(thread.is_alive())
                finally:
                    server.shutdown()
                    thread.join(timeout=3)
        finally:
            server_mod.webbrowser.open = original

    def test_occupied_port_stops_without_opening_a_browser(self):
        from bsc import server as server_mod
        import contextlib
        import io
        class Quiet(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return
            def do_GET(self):
                body = b'other'
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        opened = []
        original = server_mod.webbrowser.open
        server_mod.webbrowser.open = opened.append
        other = ThreadingHTTPServer(('127.0.0.1', 0), Quiet)
        thread = threading.Thread(target=other.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as raised:
                        serve(Path(tmp), other.server_address[1], open_browser=True, quiet=True)
            self.assertEqual(raised.exception.code, 1)
        finally:
            server_mod.webbrowser.open = original
            other.shutdown()
            other.server_close()
            thread.join(timeout=3)
        self.assertEqual(opened, [])

class FakeProvider(BaseHTTPRequestHandler):
    seen=[]
    redirect=False
    malformed=False
    def log_message(self,*args):pass
    def do_POST(self):
        data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        type(self).seen.append({'path':self.path,'data':data,'authorization':self.headers.get('Authorization')})
        if type(self).redirect:
            self.send_response(302);self.send_header('Location','https://untrusted.example.com/');self.end_headers();return
        raw=json.dumps({'choices':[{'message':{'content':'bad json' if type(self).malformed else json.dumps(PLAN)}}]}).encode()
        self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)

class ProviderTests(unittest.TestCase):
    def setUp(self):
        FakeProvider.seen=[];FakeProvider.redirect=False;FakeProvider.malformed=False
        self.server=ThreadingHTTPServer(('127.0.0.1',0),FakeProvider)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.config={'base_url':f'http://127.0.0.1:{self.server.server_port}/v1','model':'fixture-model','local':True,'api_key':'fixture-secret'}
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join()
    def call(self):return providers.draft(self.config,messages=[{'role':'user','content':'Prepare inventory'}],current_plan=None,selected_operations=[])
    def test_provider_wire_contract(self):
        self.assertEqual(self.call()['name'],'inventory-brief')
        seen=FakeProvider.seen[0]
        self.assertEqual(seen['path'],'/v1/chat/completions')
        self.assertEqual(seen['authorization'],'Bearer fixture-secret')
        self.assertNotIn('fixture-secret',json.dumps(seen['data']))
        self.assertEqual(seen['data']['response_format'],{'type':'json_object'})
        self.assertEqual(seen['data']['max_completion_tokens'], 2400)
        self.assertNotIn('Tool generation is enabled', seen['data']['messages'][0]['content'])
    def test_draft_sends_harness_actions_and_not_the_folder_path(self):
        providers.draft(self.config, messages=[{'role':'user','content':'Triage my inbox.'}], current_plan=None,
                        selected_operations=[], harness={'name':'hermes-agent-evo','skills':['email/himalaya'],
                        'tools':[{'name':'discord','actions':['list_guilds','fetch_messages']}],
                        'path': r'C:\secret\hermes-agent-evo'})
        seen = FakeProvider.seen[-1]
        packet = json.loads(seen['data']['messages'][1]['content'])
        self.assertEqual(packet['harness']['skills'], [{'name': 'email/himalaya'}])
        self.assertEqual([item['name'] for item in packet['harness']['tools'][0]['actions']],
                         ['list_guilds', 'fetch_messages'])
        self.assertNotIn('secret', json.dumps(packet['harness']))
        system = seen['data']['messages'][0]['content']
        self.assertIn('exact action', system)
        self.assertIn('Learn that contract', system)
        self.assertNotIn('subject as query', system)
        self.assertNotIn('Tool generation is enabled', system)
        self.assertNotIn('skill-authoring', seen['data']['messages'][0]['content'].split('Do not call a skill-authoring')[0])
        self.assertIn('Interlink the new skill', system)
        self.assertEqual(packet['harness']['links'], [])
    def test_draft_sends_only_the_commands_the_job_needs(self):
        from tests.test_harness import GMAIL_JOB, gmail_home
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'hermes-agent-evo'
            gmail_home(home)
            catalog = __import__('bsc.harness', fromlist=['catalog_for']).catalog_for(str(home))
        providers.draft(self.config, messages=[{'role': 'user', 'content': GMAIL_JOB}],
                        current_plan=None, selected_operations=[], harness=catalog)
        packet = json.loads(FakeProvider.seen[-1]['data']['messages'][1]['content'])
        links = {item['name']: item for item in packet['harness']['links']}
        self.assertIn('productivity/google-workspace', links)
        names = [item['name'] for item in links['productivity/google-workspace']['actions']]
        self.assertIn('gmail search', names)
        self.assertIn('gmail send', names)
        self.assertNotIn('calendar list', names)
        self.assertNotIn('unread skill body', json.dumps(packet['harness']))
        self.assertNotIn(str(home), json.dumps(packet['harness']))

    def test_no_redirect_with_credentials(self):
        FakeProvider.redirect=True
        with self.assertRaisesRegex(InputError,'HTTP 302'):self.call()
        self.assertEqual(len(FakeProvider.seen),1)
    def test_invalid_model_json_rejected(self):
        FakeProvider.malformed=True
        with self.assertRaisesRegex(InputError,'valid skill-plan'):self.call()
    def test_legacy_max_tokens_and_plain_json(self):
        self.config.update({'token_field':'max_tokens','json_mode':False});self.call()
        payload=FakeProvider.seen[0]['data'];self.assertIn('max_tokens',payload);self.assertNotIn('response_format',payload)
