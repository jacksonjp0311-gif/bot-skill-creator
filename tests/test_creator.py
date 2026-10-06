from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile
from bsc import core, openapi
from bsc.cli import dispatch
from bsc.security import InputError, endpoint, no_secrets, valid_slug
from bsc.keystore import Keystore
from bsc.workspace import Workspace

ROOT = Path(__file__).resolve().parent.parent
DOC = (ROOT / 'examples/warehouse.openapi.json').read_text()
PLAN = json.loads((ROOT / 'examples/inventory-plan.json').read_text())

class ImportTests(unittest.TestCase):
    def test_import_is_contract_only(self):
        data = openapi.import_document(DOC)
        self.assertEqual(len(data['operations']), 3)
        self.assertEqual(data['status'], 'contract_only_not_connected')
        self.assertTrue(all(o['requires_host_approval'] for o in data['operations']))
    def test_no_default_selection(self):
        files = core.compile_package(PLAN, openapi.import_document(DOC))
        self.assertEqual(json.loads(files['references/api-contract.json'])['operations'], [])
    def test_selection_excludes_other_operations(self):
        files = core.compile_package(PLAN, openapi.import_document(DOC), ['listInventory'])
        self.assertEqual([o['id'] for o in json.loads(files['references/api-contract.json'])['operations']], ['listInventory'])
    def test_unknown_operation_rejected(self):
        with self.assertRaises(InputError):
            core.compile_package(PLAN, openapi.import_document(DOC), ['invented'])
    def test_duplicate_operation_rejected(self):
        doc = json.loads(DOC)
        doc['paths']['/suppliers']['get']['operationId'] = 'listInventory'
        with self.assertRaises(InputError):
            openapi.import_document(json.dumps(doc))
    def test_external_ref_rejected(self):
        doc = json.loads(DOC)
        doc['paths']['/inventory']['get']['parameters'][0]['schema'] = {'$ref': 'https://example.com/secrets.json'}
        with self.assertRaisesRegex(InputError, 'External'):
            openapi.import_document(json.dumps(doc))
    def test_local_ref_resolved(self):
        doc = json.loads(DOC)
        doc['components']['schemas'] = {'Warehouse': {'type': 'string'}}
        doc['paths']['/inventory']['get']['parameters'][0]['schema'] = {'$ref': '#/components/schemas/Warehouse'}
        result = openapi.import_document(json.dumps(doc))
        self.assertEqual(result['operations'][0]['parameters'][0]['schema']['type'], 'string')
    def test_cycle_rejected(self):
        doc = json.loads(DOC)
        doc['components']['schemas'] = {'Loop': {'$ref': '#/components/schemas/Loop'}}
        doc['paths']['/inventory']['get']['parameters'][0]['schema'] = {'$ref': '#/components/schemas/Loop'}
        with self.assertRaisesRegex(InputError, 'Cyclic'):
            openapi.import_document(json.dumps(doc))
    def test_examples_and_defaults_not_exported(self):
        doc = json.loads(DOC)
        doc['paths']['/inventory']['get']['parameters'][0]['schema'].update({'example': 'private-example', 'default': 'private-default'})
        result = json.dumps(openapi.import_document(json.dumps(doc)))
        self.assertNotIn('private-example', result)
        self.assertNotIn('private-default', result)
    def test_invalid_version_rejected(self):
        doc = json.loads(DOC);doc['openapi'] = '2.0'
        with self.assertRaises(InputError): openapi.import_document(json.dumps(doc))
    def test_yaml_is_not_silently_parsed(self):
        with self.assertRaises(InputError): openapi.import_document('openapi: 3.1.0')
    def test_server_override_rejected(self):
        doc = json.loads(DOC);doc['paths']['/inventory']['servers'] = [{'url': 'https://example.com'}]
        with self.assertRaises(InputError): openapi.import_document(json.dumps(doc))
    def test_private_api_rejected(self):
        doc = json.loads(DOC);doc['servers'][0]['url'] = 'http://169.254.169.254/'
        with self.assertRaises(InputError): openapi.import_document(json.dumps(doc))
    def test_secret_summary_rejected(self):
        doc = json.loads(DOC);doc['paths']['/inventory']['get']['summary'] = 'Bearer ' + 'x'*30
        with self.assertRaises(InputError): openapi.import_document(json.dumps(doc))
    def test_input_untouched(self):
        raw = DOC
        openapi.import_document(raw)
        self.assertEqual(raw, DOC)

class CompilerTests(unittest.TestCase):
    def test_full_package_validates(self):
        self.assertTrue(core.validate_files(core.compile_package(PLAN))['ok'])
    def test_same_input_same_zip(self):
        first = core.compile_package(PLAN)
        second = core.compile_package(PLAN)
        self.assertEqual(core.zip_bytes(PLAN['name'], first), core.zip_bytes(PLAN['name'], second))
    def test_corruption_detected(self):
        files = core.compile_package(PLAN);files['SKILL.md'] += b'changed'
        self.assertFalse(core.validate_files(files)['ok'])
    def test_missing_checksum_coverage_detected(self):
        files = core.compile_package(PLAN);files['extra.txt'] = b'untracked'
        self.assertFalse(core.validate_files(files)['ok'])
    def test_unknown_fields_cannot_override_controls(self):
        plan = deepcopy(PLAN);plan['approval'] = False;plan['host_enforcement_required'] = False
        files = core.compile_package(plan)
        workflow = json.loads(files['references/workflow.json'])
        self.assertTrue(workflow['host_enforcement_required'])
        self.assertTrue(workflow['approval']['required_for_all_imported_api_invocations'])
    def test_slug_path_traversal_rejected(self):
        plan = deepcopy(PLAN);plan['name'] = '../../pwned'
        with self.assertRaises(InputError): core.compile_package(plan)
    def test_frontmatter_description_is_quoted(self):
        plan = deepcopy(PLAN);plan['description'] = 'Some "quotes": and\nnew lines'
        content = core.compile_package(plan)['SKILL.md'].decode()
        self.assertIn('description: ' + json.dumps(plan['description']), content)
    def test_safety_loop_present(self):
        text = core.compile_package(PLAN)['SKILL.md'].decode()
        self.assertIn('Unknown outcomes are not failures', text)
        self.assertIn('authentic approval', text)
    def test_example_and_manifest_no_live_claim(self):
        files = core.compile_package(PLAN)
        self.assertFalse(json.loads(files['skill.json'])['live_verified'])
        self.assertEqual(json.loads(files['manifest.json'])['validation_scope'], 'static_structure_and_integrity_only')
    def test_refinement_is_constraint_in_offline_mode(self):
        p = core.offline_plan('Limit report to 10 SKUs.', [], PLAN)
        self.assertEqual(p['constraints'][-1], 'Limit report to 10 SKUs.')
    def test_destination_not_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            core.write_package(Path(d), PLAN)
            with self.assertRaises(InputError): core.write_package(Path(d), PLAN)
    def test_export_script_runs(self):
        with tempfile.TemporaryDirectory() as d:
            out = core.write_package(Path(d), PLAN)
            result = subprocess.run([sys.executable, str(out/'scripts/validate.py')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(result.stdout)['ok'])
    def test_zip_roundtrip(self):
        files = core.compile_package(PLAN)
        with zipfile.ZipFile(BytesIO(core.zip_bytes(PLAN['name'], files))) as z:
            self.assertIsNone(z.testzip())
            self.assertEqual(len(z.namelist()), 9)
    def test_tool_generation_runs_and_refuses_live_actions(self):
        plain = core.compile_package(PLAN)
        self.assertNotIn('tools/run_tool.py', plain)
        files = core.compile_package(PLAN, tool_generation=True)
        self.assertTrue(core.validate_files(files)['ok'])
        self.assertIn('tools/run_tool.py', files)
        self.assertIn('Local tool', files['SKILL.md'].decode())
        self.assertTrue(json.loads(files['skill.json'])['tool_generation'])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / 'run_tool.py'
            script.write_bytes(files['tools/run_tool.py'])
            missing = subprocess.run([sys.executable, str(script)], input='{}', capture_output=True, text=True)
            self.assertEqual(missing.returncode, 0, missing.stderr)
            self.assertEqual(json.loads(missing.stdout)['outcome'], 'NEEDS_INPUT')
            supplied = {'inputs': {item: 'sample' for item in PLAN['inputs']}}
            ready = subprocess.run([sys.executable, str(script)], input=json.dumps(supplied), capture_output=True, text=True)
            self.assertEqual(json.loads(ready.stdout)['outcome'], 'DRAFT')
            self.assertFalse(json.loads(ready.stdout)['network'])
            refused = subprocess.run([sys.executable, str(script)], input=json.dumps({'requested_effect': 'send mail', 'inputs': supplied['inputs']}), capture_output=True, text=True)
            self.assertEqual(json.loads(refused.stdout)['outcome'], 'REFUSED')
    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d);(root/'file').write_text('hi')
            try: (root/'link').symlink_to(root/'file')
            except OSError: self.skipTest('Symlink creation requires permission on this platform.')
            with self.assertRaises(InputError): core.read_package(root)

    def test_renamed_folder_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            out = core.write_package(Path(d), PLAN)
            moved = out.rename(Path(d) / 'different-name')
            with self.assertRaisesRegex(InputError, 'folder name'):
                core.read_package(moved)
    def test_standalone_extra_file_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            out = core.write_package(Path(d), PLAN)
            (out / 'extra.txt').write_text('untracked')
            result = subprocess.run([sys.executable, str(out/'scripts/validate.py')], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)

class BoundaryTests(unittest.TestCase):
    def test_private_model_addresses_rejected(self):
        for address in ['http://example.com/v1', 'https://10.0.0.1/v1', 'https://127.0.0.1/v1', 'https://metadata.google.internal/v1']:
            with self.subTest(address=address), self.assertRaises(InputError): endpoint(address)
    def test_literal_loopback_opt_in(self):
        self.assertEqual(endpoint('http://127.0.0.1:1234/v1', local=True), 'http://127.0.0.1:1234/v1')
    def test_key_in_url_rejected(self):
        for url in ['https://me:secret@example.com/v1', 'https://example.com/v1?key=abc', 'https://example.com/v1#abc']:
            with self.assertRaises(InputError): endpoint(url)
    def test_secrets_blocked(self):
        for value in ['sk-'+'a'*32, 'Bearer '+'b'*32, '-----BEGIN PRIVATE KEY-----']:
            with self.assertRaises(InputError): no_secrets(value)
    def test_score_identity(self):
        r = core.score(8,1,1)
        self.assertAlmostEqual(r['q'] * r['mu'], r['theta'])
        self.assertAlmostEqual(r['theta'], 9/13)
    def test_unknown_does_not_change_mu(self):
        self.assertEqual(core.score(8,1,0)['mu'], core.score(8,1,4)['mu'])
    def test_bad_counts_fail(self):
        for args in [(-1,0,0),(0.5,0,0),(True,0,0)]:
            with self.assertRaises(ValueError): core.score(*args)
    def test_nan_cost_fails(self):
        with self.assertRaises(InputError): core.score(cost=float('nan'))

class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.secrets = tempfile.TemporaryDirectory()
        self.ws = Workspace(Path(self.tmp.name), Keystore(Path(self.secrets.name)))
        self.project = self.ws.create()
    def tearDown(self):
        self.secrets.cleanup(); self.tmp.cleanup()
    def draft(self): return self.ws.chat(self.project['id'], 'Create an inventory report, read only.')
    def test_save_and_reopen(self):
        p=self.draft(); self.assertEqual(self.ws.get(p['id'])['plan'], p['plan'])
    def test_stale_export_approval_rejected(self):
        p=self.draft(); self.ws.chat(p['id'], 'Keep the report under one page.')
        with self.assertRaisesRegex(InputError, 'changed'): self.ws.export(p['id'], p['export_fingerprint'])
    def test_gated_export_and_replay(self):
        p=self.draft(); first=self.ws.export(p['id'],p['export_fingerprint']); second=self.ws.export(p['id'],p['export_fingerprint'])
        self.assertEqual(first, second)
        self.assertEqual(len(list((Path(self.tmp.name)/'exports').glob('*.zip'))), 1)
    def test_restart_replays_completed_export_without_new_dispatch(self):
        p=self.draft(); first=self.ws.export(p['id'],p['export_fingerprint'])
        restarted=Workspace(Path(self.tmp.name))
        self.assertEqual(first, restarted.export(p['id'],p['export_fingerprint']))
    def test_chat_saves_tool_generation_and_can_turn_it_off(self):
        drafted = self.ws.chat(self.project['id'], 'Create a skill that summarizes three pasted notes.', tool_generation=True)
        self.assertTrue(drafted['tool_generation'])
        self.assertIn('tools/run_tool.py', drafted['files'])
        self.assertTrue(drafted['validation']['ok'])
        quiet = self.ws.set_tool_generation(drafted['id'], False)
        self.assertFalse(quiet['tool_generation'])
        self.assertNotIn('tools/run_tool.py', quiet['files'])
        self.assertTrue(quiet['validation']['ok'])
    def test_model_key_not_saved(self):
        self.ws.configure_provider({'base_url':'http://127.0.0.1:1234/v1','model':'test','api_key':'test-private-secret','local':True})
        self.assertNotIn('api_key', self.ws.provider_info())
        for path in Path(self.tmp.name).rglob('*.json'): self.assertNotIn('test-private-secret',path.read_text())
        for path in Path(self.secrets.name).rglob('*'):
            if path.is_file(): self.assertNotIn(b'test-private-secret', path.read_bytes())
    def test_traversal_project_id_rejected(self):
        with self.assertRaises(InputError): self.ws.get('../../etc/passwd')
    def test_delete_removes_only_that_draft(self):
        other=self.ws.create(); p=self.draft()
        self.assertEqual(self.ws.delete(p['id'])['deleted'], p['id'])
        with self.assertRaisesRegex(InputError, 'not found'): self.ws.get(p['id'])
        self.assertEqual(self.ws.get(other['id'])['id'], other['id'])
    def test_local_model_discovery_reads_loopback_server(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from bsc.discover import discover_local_models
        payload=json.dumps({'models':[{'name':r'C:\models\Qwen3.6-35B-A3B-Q4_K_M.gguf','model':r'C:\models\Qwen3.6-35B-A3B-Q4_K_M.gguf','details':{'parameter_size':'','quantization_level':''}}],'object':'list','data':[{'id':r'C:\models\Qwen3.6-35B-A3B-Q4_K_M.gguf','object':'model','owned_by':'llamacpp','meta':{'n_params':34660610688,'n_ctx':65536,'ftype':'Q4_K - Medium'}}]}).encode()
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path!='/v1/models':
                    self.send_error(404);return
                self.send_response(200)
                self.send_header('Content-Type','application/json')
                self.send_header('Server','llama.cpp')
                self.send_header('Content-Length',str(len(payload)))
                self.end_headers();self.wfile.write(payload)
            def log_message(self,*args): return
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            found=discover_local_models([f'http://127.0.0.1:{server.server_address[1]}/v1'], timeout=1)
            self.assertEqual(len(found['models']),1)
            model=found['models'][0]
            self.assertEqual(model['label'],'Qwen3.6-35B-A3B')
            self.assertTrue(model['id'].endswith('Qwen3.6-35B-A3B-Q4_K_M.gguf'))
            self.assertEqual(model['server'],'llama.cpp')
            self.assertFalse(model['json_mode'])
            self.assertEqual(model['token_field'],'max_tokens')
            self.assertTrue(model['local'])
            self.assertIn('64K context', model['detail'])
            self.assertIn('34.7B', model['detail'])
            self.assertIn('Q4_K - Medium', model['detail'])
            self.assertEqual(discover_local_models(['https://example.com/v1'], timeout=1)['models'],[])
        finally:
            server.shutdown();server.server_close();thread.join()
    def test_default_discovery_reads_ollama_only(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from bsc.discover import discover_local_models
        payload=json.dumps({'models':[
            {'name':'llama3.2:latest','model':'llama3.2:latest','details':{'parameter_size':'3.2B','quantization_level':'Q4_K_M','family':'llama'}},
            {'name':'pegasus-harness','model':'pegasus-harness','details':{'parameter_size':'1B','quantization_level':'Q4_0'}},
            {'name':r'C:\models\skip-me.gguf','model':r'C:\models\skip-me.gguf','details':{}},
        ]}).encode()
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path!='/api/tags':
                    self.send_error(404);return
                self.send_response(200);self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
            def log_message(self,*args): return
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            found=discover_local_models(timeout=1, ollama_origin=f'http://127.0.0.1:{server.server_address[1]}')
            self.assertEqual([model['id'] for model in found['models']], ['llama3.2:latest'])
            model=found['models'][0]
            self.assertEqual(model['label'], 'llama3.2')
            self.assertEqual(model['server'], 'Ollama')
            self.assertTrue(model['base_url'].endswith('/v1'))
            self.assertIn('3.2B', model['detail'])
            self.assertIn('Q4_K_M', model['detail'])
            self.assertFalse(model['json_mode'])
            self.assertNotIn('api_key', model)
            live=discover_local_models(timeout=0.3)
            for item in live['models']:
                self.assertIn(':11434', item['base_url'])
                self.assertNotIn('pegasus', item['id'].lower())
        finally:
            server.shutdown();server.server_close();thread.join()
    def test_keystore_seals_a_remote_key_outside_the_workspace(self):
        secret='sk-test-not-a-real-key'
        saved=self.ws.save_provider_key('openai', secret)
        self.assertEqual(saved['confirmation'], 'Saved for the next session.')
        self.assertNotIn('api_key', saved)
        self.assertNotIn(secret, json.dumps(saved))
        blob=(Path(self.secrets.name)/'openai.key').read_bytes()
        self.assertNotIn(secret.encode(), blob)
        self.assertEqual(self.ws.keystore.load('openai'), secret)
        info=self.ws.configure_provider({'provider_id':'openai','base_url':'https://api.openai.com/v1','model':'gpt-4o','api_key':''})
        self.assertNotIn('api_key', info)
        self.assertTrue(info['key_saved'])
        self.assertEqual(self.ws.provider['api_key'], secret)
        self.assertNotIn('provider_id', self.ws.provider)
        for path in Path(self.tmp.name).rglob('*'):
            if path.is_file(): self.assertNotIn(secret.encode(), path.read_bytes())
        with self.assertRaisesRegex(InputError, 'remote provider'): self.ws.save_provider_key('local', secret)
        with self.assertRaisesRegex(InputError, 'Enter the key'): self.ws.save_provider_key('grok', '   ')
        status=self.ws.secret_status()
        self.assertEqual(status['saved_keys'], ['openai'])
        self.assertNotIn(secret, json.dumps(status))
    def test_ollama_choice_is_remembered_without_a_key(self):
        info=self.ws.configure_provider({'provider_id':'local','base_url':'http://127.0.0.1:11434/v1','model':'llama3.2:latest','api_key':'','local':True,'json_mode':False,'token_field':'max_tokens'})
        self.assertEqual(info['confirmation'], 'Saved for the next session. No API key is used.')
        self.assertNotIn('api_key', info)
        stored=(Path(self.secrets.name)/'ollama.json').read_text(encoding='utf-8')
        self.assertIn('llama3.2:latest', stored)
        self.assertNotIn('api_key', stored)
        self.ws.configure_provider({'base_url':'http://127.0.0.1:8080/v1','model':'Qwen3.6-35B-A3B','api_key':'','local':True,'token_field':'max_tokens','json_mode':False})
        preference=self.ws.keystore.local_preference()
        self.assertEqual(preference['base_url'], 'http://127.0.0.1:11434/v1')
        self.assertEqual(preference['model'], 'llama3.2:latest')
        (Path(self.secrets.name)/'ollama.json').write_text(json.dumps({'base_url':'http://127.0.0.1:8080/v1','model':'qwen'}), encoding='utf-8')
        self.assertIsNone(self.ws.keystore.local_preference())
    def test_delete_rejects_bad_id(self):
        with self.assertRaises(InputError): self.ws.delete('../secret')
        with self.assertRaisesRegex(InputError, 'not found'): self.ws.delete('a'*32)
    def test_import_resets_selection(self):
        p=self.ws.import_api(self.project['id'],DOC)
        p=self.ws.select(p['id'],['listInventory'])
        self.assertEqual(self.ws.import_api(p['id'],DOC)['selected_ids'],[])
    def test_bridge_preview_no_file_write(self):
        result=dispatch({'action':'preview','brief':'Draft an inventory brief','name':'my-brief'})
        self.assertTrue(result['validation']['ok'])
    def test_bridge_unknown_action_rejected(self):
        with self.assertRaises(InputError): dispatch({'action':'execute-api'})
