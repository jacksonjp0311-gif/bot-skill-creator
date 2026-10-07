from pathlib import Path
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from bsc.harness import accept_path, find_homes
from bsc.keystore import Keystore
from bsc.security import InputError
from bsc.server import AppServer
from bsc.workspace import Workspace

SECRET = 'sk-this-is-not-a-real-key'
MEMORY = 'the private memory sentence stays on disk'


def home_fixture(root: Path) -> None:
    (root / 'skills' / 'demo').mkdir(parents=True)
    (root / 'skills' / 'demo' / 'SKILL.md').write_text('skill body stays unread\n', encoding='utf-8')
    (root / 'memories').mkdir()
    (root / 'memories' / 'MEMORY.md').write_text(MEMORY + '\n', encoding='utf-8')
    (root / '.env').write_text('API_KEY=' + SECRET + '\n', encoding='utf-8')
    (root / 'config.yaml').write_text(
        'model: demo\n'
        'profile: local\n'
        'toolsets:\n'
        '  - memory\n'
        '  - terminal\n'
        'api_key: ' + SECRET + '\n',
        encoding='utf-8')


class HarnessTests(unittest.TestCase):
    def test_find_reports_markers_and_skips_plain_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / 'hermes'
            home_fixture(home)
            plain = root / 'plain'
            plain.mkdir()
            found = find_homes(roots=[home, plain])['homes']
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]['path'], str(home.resolve()))
            self.assertIn('config.yaml', found[0]['markers'])
            self.assertIn('.env', found[0]['markers'])
            self.assertEqual(found[0]['skill_count'], 1)
            self.assertEqual(found[0]['memory_files'], ['MEMORY.md'])
            self.assertEqual(found[0]['tool_count'], 2)
            self.assertNotIn(SECRET, json.dumps(found))
            self.assertNotIn(MEMORY, json.dumps(found))

    def test_accept_keeps_secrets_and_memory_text_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'hermes'
            home_fixture(home)
            profile = accept_path(str(home))
            blob = json.dumps(profile)
            self.assertNotIn(SECRET, blob)
            self.assertNotIn(MEMORY, blob)
            self.assertNotIn('skill body stays unread', blob)
            self.assertTrue(profile['agreed'])
            self.assertTrue(profile['accepted'])
            labels = [node['label'] for node in profile['nexus']['nodes']]
            self.assertIn('demo', labels)
            self.assertIn('MEMORY.md', labels)
            self.assertIn('memory', labels)
            self.assertIn('terminal', labels)
            self.assertNotIn('api_key', labels)
            sections = [row['name'] for row in profile['directory']['children'][3]['children']]
            self.assertIn('model', sections)
            self.assertIn('toolsets', sections)
            self.assertNotIn('api_key', sections)

    def test_desktop_checkout_is_found_without_a_config_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            desk = Path(tmp) / 'Desktop'
            checkout = desk / 'hermes-agent-evo'
            skill = checkout / 'skills' / 'email' / 'inbox'
            skill.mkdir(parents=True)
            (skill / 'SKILL.md').write_text('unread skill body\n', encoding='utf-8')
            (checkout / 'tools').mkdir()
            (checkout / 'tools' / 'browser_tool.py').write_text('print(1)\n', encoding='utf-8')
            (checkout / 'SOUL.md').write_text('soul\n', encoding='utf-8')
            (desk / 'notes').mkdir()
            found = find_homes(roots=[], desks=[desk])['homes']
            self.assertEqual([item['name'] for item in found], ['hermes-agent-evo'])
            self.assertIn('SOUL.md', found[0]['markers'])
            self.assertIn('skills', found[0]['markers'])
            quoted = accept_path('"' + str(checkout) + '"')
            self.assertEqual(quoted['path'], str(checkout.resolve()))
            climbed = accept_path(str(skill))
            self.assertEqual(climbed['path'], str(checkout.resolve()))
            labels = [node['label'] for node in quoted['nexus']['nodes']]
            self.assertIn('email/inbox', labels)
            self.assertIn('browser', labels)
            self.assertNotIn('unread skill body', json.dumps(quoted))

    def test_workspace_refuses_accept_without_agreement(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as secrets:
            home = Path(tmp) / 'hermes'
            home_fixture(home)
            ws = Workspace(Path(tmp) / 'studio', Keystore(Path(secrets)))
            with self.assertRaises(InputError):
                ws.accept_harness(str(home), False)
            self.assertFalse(ws.harness_profile()['accepted'])
            saved = ws.accept_harness(str(home), True)
            self.assertTrue(saved['accepted'])
            self.assertNotIn(SECRET, (ws.path / 'harness' / 'profile.json').read_text(encoding='utf-8'))
            self.assertEqual(ws.harness_profile()['path'], str(home.resolve()))
            cleared = ws.remove_harness()
            self.assertFalse(cleared['accepted'])
            self.assertFalse(ws.harness_profile()['accepted'])
            self.assertFalse((ws.path / 'harness' / 'profile.json').exists())
            self.assertTrue((home / 'skills' / 'demo' / 'SKILL.md').is_file())
            self.assertEqual(ws.remove_harness(), {'accepted': False})

    def test_draft_uses_the_accepted_harness_without_being_told_the_names(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as secrets:
            home = Path(tmp) / 'hermes-agent-evo'
            (home / 'skills' / 'email' / 'email-inbox-triage').mkdir(parents=True)
            (home / 'skills' / 'email' / 'email-inbox-triage' / 'SKILL.md').write_text('name: email-inbox-triage\n', encoding='utf-8')
            (home / 'skills' / 'email' / 'himalaya').mkdir(parents=True)
            (home / 'skills' / 'email' / 'himalaya' / 'SKILL.md').write_text('name: himalaya\n', encoding='utf-8')
            (home / 'skills' / 'notes').mkdir()
            (home / 'skills' / 'notes' / 'SKILL.md').write_text('name: notes\n', encoding='utf-8')
            (home / 'SOUL.md').write_text('soul\n', encoding='utf-8')
            (home / 'tools').mkdir()
            (home / 'tools' / 'memory_tool.py').write_text('print(1)\n', encoding='utf-8')
            ws = Workspace(Path(tmp) / 'studio', Keystore(Path(secrets)))
            ws.accept_harness(str(home), True)
            project = ws.create()
            drafted = ws.chat(project['id'], 'Triage my inbox and draft the replies for me to approve.')
            body = json.dumps(drafted['plan'])
            self.assertIn('email/email-inbox-triage', body)
            self.assertIn('email/himalaya', body)
            self.assertNotIn('notes', body)
            self.assertNotIn(str(home), body)


class HarnessHTTPTests(unittest.TestCase):
    def test_routes_require_agreement_and_hide_secrets(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as secrets:
            home = Path(tmp) / 'hermes'
            home_fixture(home)
            ws = Workspace(Path(tmp) / 'studio', Keystore(Path(secrets)))
            server = AppServer(('127.0.0.1', 0), ws)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                def request(path, data=None, token=True):
                    headers = {'Content-Type': 'application/json'}
                    if token:
                        headers['X-BSC-Token'] = server.token
                    body = None if data is None else json.dumps(data).encode()
                    req = urllib.request.Request(server.origin + path, data=body, headers=headers)
                    return urllib.request.urlopen(req, timeout=5)

                with self.assertRaises(urllib.error.HTTPError) as blocked:
                    request('/api/harness', token=False)
                self.assertEqual(blocked.exception.code, 403)
                with request('/api/harness') as response:
                    self.assertFalse(json.load(response)['accepted'])
                with self.assertRaises(urllib.error.HTTPError) as early:
                    request('/api/harness/accept', {'path': str(home), 'agreed': False})
                self.assertEqual(early.exception.code, 400)
                # Point the finder at the fixture by accepting the verified path directly.
                with request('/api/harness/accept', {'path': str(home), 'agreed': True}) as response:
                    profile = json.load(response)
                self.assertTrue(profile['accepted'])
                self.assertNotIn(SECRET, json.dumps(profile))
                self.assertNotIn(MEMORY, json.dumps(profile))
                with request('/api/harness/remove', {}) as response:
                    self.assertFalse(json.load(response)['accepted'])
                with request('/api/harness') as response:
                    self.assertFalse(json.load(response)['accepted'])
                self.assertTrue((home / 'config.yaml').is_file())
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
