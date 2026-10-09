from pathlib import Path
import json
import tempfile
import threading
import unittest
from unittest.mock import patch

from bsc import contracts, core, harness
from bsc.keystore import Keystore
from bsc.security import InputError
from bsc.workspace import Workspace
from bsc.cli import dispatch
from bsc.server import AppServer
import urllib.request
import urllib.error


def fixture(path, tool='memory', action='add'):
    (path / 'skills').mkdir(parents=True)
    (path / 'SOUL.md').write_text('Fixture only.', encoding='utf-8')
    (path / 'tools').mkdir()
    (path / 'tools' / (tool + '_tool.py')).write_text(
        'ACTIONS = {"' + action + '": None}\nSCHEMA = ' + repr({
            'name': tool, 'parameters': {'type': 'object',
                'properties': {'content': {'type': 'string'}}, 'required': ['content']}}), encoding='utf-8')


class HarnessWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.a, self.b = self.root / 'hermes-a', self.root / 'hermes-b'
        fixture(self.a)
        fixture(self.b, 'calendar', 'list_events')
        self.ws = Workspace(self.root / 'studio', Keystore(self.root / 'secrets'))
        self.a_id = self.ws.accept_harness(str(self.a), True)['id']

    def draft(self):
        return self.ws.chat(self.ws.create()['id'], 'Save a memory note.')

    def test_chat_only_drafts_and_install_is_revision_bound(self):
        p = self.draft()
        self.assertTrue(p['sandbox']['ok'], p['sandbox'])
        self.assertTrue(p['install']['installed'])
        self.assertTrue((self.a / 'skills/custom').exists())
        with self.assertRaises(InputError):
            self.ws.install(p['id'], p['install_fingerprint'], False)
        changed = self.ws.edit_plan(p['id'], {**p['plan'], 'description': 'Changed purpose.'})
        self.assertIsNone(changed['sandbox'])
        with self.assertRaises(InputError):
            self.ws.install(p['id'], p['install_fingerprint'], True)
        validated = self.ws.validate(p['id'])
        installed = self.ws.install(p['id'], validated['install_fingerprint'], True)
        self.assertFalse(installed['install']['installed'])
        self.assertIn('not overwritten', installed['install']['reason'])
        self.assertEqual(installed['install']['harness_id'], self.a_id)

    def test_switch_and_restart_preserve_context_and_draft_target(self):
        p = self.draft()
        self.ws.set_harness_context(self.a_id, 'Keep note summaries concise.')
        b_id = self.ws.accept_harness(str(self.b), True)['id']
        self.assertEqual(self.ws.list(), [])
        self.ws.set_harness_context(b_id, 'Calendar uses UTC.')
        self.assertEqual(self.ws.create()['harness_id'], b_id)
        continued = self.ws.chat(p['id'], 'Keep the memory note concise.')
        self.assertEqual(continued['harness_id'], self.a_id)
        self.assertIn('memory', json.dumps(continued['plan']))
        self.assertFalse(continued['install']['installed'])
        self.assertIn('not overwritten', continued['install']['reason'])
        self.assertTrue((self.a / 'skills/custom').exists())
        self.assertFalse((self.b / 'skills/custom').exists())
        again = Workspace(self.ws.path, Keystore(self.root / 'secrets'))
        self.assertEqual(len(again.harness_list()['harnesses']), 2)
        again.switch_harness(self.a_id)
        self.assertEqual([x['id'] for x in again.list()], [p['id']])
        self.assertEqual(again.harnesses.get(self.a_id)['context'], 'Keep note summaries concise.')
        self.assertEqual(again.harnesses.get(b_id)['context'], 'Calendar uses UTC.')

    def test_explicit_creation_target_survives_other_tab_switch(self):
        self.ws.accept_harness(str(self.b), True)
        p = self.ws.create(self.a_id)
        self.assertEqual(p['harness_id'], self.a_id)
        self.assertIsNone(self.ws.create(None)['harness_id'])
        with self.assertRaises(InputError):
            self.ws.create('0' * 32)

    def test_capability_change_invalidates_approval(self):
        p = self.draft()
        tool = self.a / 'tools/memory_tool.py'
        tool.write_text(tool.read_text().replace('"add"', '"remove"'))
        with self.assertRaisesRegex(InputError, 'capabilities changed'):
            self.ws.install(p['id'], p['install_fingerprint'], True)
        with self.assertRaises(InputError):
            self.ws.export(p['id'], p['export_fingerprint'])
        p = self.ws.validate(p['id'])
        self.assertFalse(p['sandbox']['ok'])
        with self.assertRaisesRegex(InputError, 'validation failed'):
            self.ws.install(p['id'], p['install_fingerprint'], True)

    def test_unavailable_harness_never_falls_back_to_active_harness(self):
        p = self.draft()
        self.ws.accept_harness(str(self.b), True)
        self.a.rename(self.root / 'moved-a')
        with self.assertRaises(InputError):
            self.ws.chat(p['id'], 'Continue.')
        self.assertFalse((self.b / 'skills/custom').exists())

    def test_validation_feedback_is_scoped_to_snapshot_and_harness(self):
        p = self.draft()
        self.ws.set_harness_context(self.a_id, 'Prefer short reports.')
        b_id = self.ws.accept_harness(str(self.b), True)['id']
        record_a = self.ws.harnesses.get(self.a_id)
        record_b = self.ws.harnesses.get(b_id)
        self.assertEqual(len(record_a['evidence']), 1)
        self.assertEqual(record_b['evidence'], [])
        received = []
        def model(config, **kwargs):
            received.append(kwargs['harness'])
            return p['plan']
        self.ws.provider = {'model': 'fixture', 'api_key': ''}
        with patch('bsc.workspace.providers.draft', side_effect=model):
            self.ws.chat(p['id'], 'Keep the memory note.')
        self.assertEqual(received[0]['creator_context'], 'Prefer short reports.')
        self.assertEqual(received[0]['previous_checks'][0]['kind'], 'static_validation')
        self.assertNotIn('calendar', json.dumps(received))
        self.assertNotIn(str(self.a), json.dumps(received))

    def test_switch_during_model_request_cannot_retarget_run(self):
        p = self.draft()
        b_id = self.ws.accept_harness(str(self.b), True)['id']
        entered, release = threading.Event(), threading.Event()
        results, failures = [], []
        def model(config, **kwargs):
            entered.set()
            self.assertTrue(release.wait(5))
            return p['plan']
        def draft():
            try:
                results.append(self.ws.chat(p['id'], 'Keep the memory note.'))
            except Exception as exc:
                failures.append(exc)
        self.ws.provider = {'model': 'fixture', 'api_key': ''}
        with patch('bsc.workspace.providers.draft', side_effect=model):
            worker = threading.Thread(target=draft)
            worker.start()
            self.assertTrue(entered.wait(5))
            switch = threading.Thread(target=lambda: self.ws.switch_harness(b_id))
            switch.start()
            release.set()
            worker.join(5)
            switch.join(5)
        self.assertFalse(failures)
        self.assertEqual(results[0]['harness_id'], self.a_id)
        self.assertEqual(self.ws.harness_profile()['id'], b_id)
        self.assertTrue((self.a / 'skills/custom').exists())
        self.assertFalse((self.b / 'skills/custom').exists())

    def test_legacy_drafts_remain_unbound(self):
        self.ws.remove_harness()
        p = self.ws.create()
        raw = self.ws.get(p['id'])
        del raw['harness_id']
        self.ws.save(raw)
        self.ws.switch_harness(self.a_id)
        updated = self.ws.chat(p['id'], 'Make a checklist.')
        self.assertIsNone(updated['target'])
        self.assertFalse(updated['install']['installed'])

    def test_bridge_uses_same_workspace_and_approval_contract(self):
        request = {'action': 'workspace', 'workspace': str(self.ws.path)}
        p = dispatch({**request, 'operation': 'create'})
        draft = dispatch({**request, 'operation': 'chat', 'id': p['id'], 'message': 'Save a memory note.'})
        self.assertEqual(draft['harness_id'], self.a_id)
        self.assertTrue(draft['install']['installed'])
        with self.assertRaises(InputError):
            dispatch({**request, 'operation': 'install', 'id': p['id'],
                      'fingerprint': draft['install_fingerprint'], 'approved': False})
        installed = dispatch({**request, 'operation': 'install', 'id': p['id'],
                              'fingerprint': draft['install_fingerprint'], 'approved': True})
        self.assertFalse(installed['install']['installed'])
        self.assertIn('not overwritten', installed['install']['reason'])

    def test_http_install_requires_token_approval_and_review(self):
        server = AppServer(('127.0.0.1', 0), self.ws)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def request(route, body=None, token=True):
            req = urllib.request.Request(server.origin + route,
                data=json.dumps(body).encode() if body is not None else None,
                headers={'Content-Type': 'application/json', 'X-BSC-Token': server.token if token else ''})
            with urllib.request.urlopen(req, timeout=5) as response:
                return json.load(response)
        try:
            with self.assertRaises(urllib.error.HTTPError):
                request('/api/harnesses', token=False)
            self.assertEqual(request('/api/harnesses')['active_id'], self.a_id)
            p = request('/api/projects', {})
            p = request('/api/chat', {'id': p['id'], 'message': 'Save a memory note.'})
            self.assertTrue(p['install']['installed'])
            self.assertTrue((self.a / 'skills/custom').exists())
            body = {'id': p['id'], 'fingerprint': p['install_fingerprint'], 'approved': True}
            with self.assertRaises(urllib.error.HTTPError):
                request('/api/install', body, token=False)
            with self.assertRaises(urllib.error.HTTPError):
                request('/api/install', {**body, 'approved': False})
            again = request('/api/install', body)
            self.assertFalse(again['install']['installed'])
            self.assertIn('not overwritten', again['install']['reason'])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


class ContractTests(unittest.TestCase):
    def test_template_uses_only_requested_tools_and_actions(self):
        catalog = {'tools': [
            {'name': 'discord', 'actions': ['list_guilds', 'list_channels', 'list_roles', 'delete_message']},
            {'name': 'computer_use', 'actions': ['computer_use']},
            {'name': 'react_to_message', 'actions': ['react_to_message']}],
            'skill_contracts': [{'name': 'unrelated/search', 'summary': 'List and search channels.',
                                 'actions': [{'name': 'list channels', 'kind': 'command'}]}]}
        p = core.offline_plan('Use Discord to list guilds and list channels. Never delete messages.', [], harness=catalog)
        self.assertEqual({(c['name'], c['action']) for c in p['capability_calls']},
                         {('discord', 'list_guilds'), ('discord', 'list_channels')})
        self.assertEqual(len(p['capability_calls']), 2)

    def test_invented_action_and_missing_input_fail(self):
        catalog = {'tools': [{'name': 'memory', 'actions': [{'name': 'add', 'requires': ['content']}]}]}
        plan = core.offline_plan('Save a note.', [])
        plan['steps'] = ['Call memory teleport_money with destination and amount.']
        self.assertIn('Unrecognized explicit call: memory teleport_money', ' '.join(contracts.errors(plan, catalog)))
        plan['steps'] = ['Call memory.add with content.']
        plan['capability_calls'] = [{'kind': 'tool', 'name': 'memory', 'action': 'add', 'inputs': {}}]
        self.assertIn('Missing inputs', ' '.join(contracts.errors(plan, catalog)))
        plan['capability_calls'][0]['inputs'] = {'content': 'The note supplied by the user.'}
        self.assertEqual(contracts.errors(plan, catalog), [])
        plan['capability_calls'][0]['inputs']['invented'] = 'Unknown field.'
        self.assertIn('Undocumented inputs', ' '.join(contracts.errors(plan, catalog)))
        del plan['capability_calls'][0]['inputs']['invented']
        plan['capability_calls'][0]['name'] = 'calendar'
        self.assertIn('Unsupported harness call', ' '.join(contracts.errors(plan, catalog)))

    def test_optional_command_flags_and_headings_are_valid_calls(self):
        catalog = {'skill_contracts': [
            {'name': 'productivity/google-workspace', 'actions': [
                {'name': 'gmail modify', 'kind': 'command', 'requires': ['MESSAGE_ID'],
                 'note': 'optional --add-labels, --remove-labels'}]},
            {'name': 'email/email-inbox-triage', 'actions': [
                {'name': 'Calibrate the user voice', 'kind': 'heading', 'requires': []}]},
        ]}
        plan = {'steps': ['Use email/email-inbox-triage. Call gmail modify with MESSAGE_ID.'],
                'capability_calls': [
                    {'kind': 'skill', 'name': 'email/email-inbox-triage',
                     'action': 'Calibrate the user voice', 'inputs': {}},
                    {'kind': 'skill', 'name': 'productivity/google-workspace', 'action': 'gmail modify',
                     'inputs': {'MESSAGE_ID': 'From the search result.',
                                '--add-labels': 'The label the user named.',
                                '--remove-labels': 'The label the user named.'}},
                ]}
        self.assertEqual(contracts.errors(plan, catalog), [])
        plan['steps'] = ['Call productivity/google-workspace action `gmail modify` with MESSAGE_ID.']
        self.assertEqual(contracts.errors(plan, catalog), [])
        plan['steps'] = ['Do not call a separate related skill for Gmail commands.']
        self.assertEqual(contracts.errors(plan, catalog), [])
        plan['steps'] = ['Call the inbox, then draft a reply for the business.']
        self.assertEqual(contracts.errors(plan, catalog), [])
        plan['steps'] = ['Do not call a related skill when the chosen skill already lists the actions.']
        self.assertEqual(contracts.errors(plan, catalog), [])
        plan['capability_calls'] = [plan['capability_calls'][0]]
        plan['steps'] = ['Call gmail modify with MESSAGE_ID.']
        self.assertIn('Declare the exact capability call', ' '.join(contracts.errors(plan, catalog)))

    def test_uninspected_tool_has_no_invented_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'hermes'
            fixture(home)
            (home / 'tools/memory_tool.py').write_text('def hidden_runtime(): pass')
            catalog = harness.catalog_for(str(home))
            memory = next(x for x in catalog['tools'] if x['name'] == 'memory')
            self.assertEqual(memory['actions'], [])
            self.assertEqual(core.tool_entries(catalog)[0]['actions'], [])
