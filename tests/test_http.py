from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from bsc import providers
from bsc.keystore import Keystore
from bsc.server import AppServer
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
        return urllib.request.urlopen(req,timeout=5)
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
    def test_tool_generation_route_adds_the_local_tool(self):
        with self.request('/api/projects', {}) as response:
            project = json.load(response)
        with self.request('/api/chat', {'id': project['id'], 'message': 'Build a read-only inventory brief.'}) as response:
            project = json.load(response)
        self.assertNotIn('tools/run_tool.py', project['files'])
        with self.request('/api/tool-generation', {'id': project['id'], 'enabled': True}) as response:
            project = json.load(response)
        self.assertTrue(project['tool_generation'])
        self.assertIn('does not call the network', project['files']['tools/run_tool.py'])
        self.assertNotIn('api_key', json.dumps(project['files']))
    def test_create_chat_export(self):
        with self.request('/api/projects',{}) as r:p=json.load(r)
        with self.request('/api/chat',{'id':p['id'],'message':'Build a read-only inventory brief.'}) as r:p=json.load(r)
        self.assertTrue(p['validation']['ok'])
        with self.request('/api/export',{'id':p['id'],'fingerprint':p['export_fingerprint']}) as r:
            self.assertEqual(r.headers['Content-Type'],'application/zip');self.assertTrue(r.read().startswith(b'PK'))
    def test_public_bind_refused(self):
        with self.assertRaises(ValueError):AppServer(('0.0.0.0',0),self.ws)

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
    def test_tool_generation_asks_the_model_for_a_longer_draft(self):
        providers.draft(self.config, messages=[{'role':'user','content':'Prepare inventory'}], current_plan=None, selected_operations=[], tool_generation=True)
        seen = FakeProvider.seen[-1]
        self.assertEqual(seen['data']['max_completion_tokens'], 4000)
        self.assertIn('Tool generation is enabled', seen['data']['messages'][0]['content'])
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
