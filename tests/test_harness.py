from pathlib import Path
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from bsc.core import bind_harness, interlink_gaps, sandbox_package
from bsc.harness import accept_path, catalog_for, find_homes
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

    def test_catalog_keeps_discord_actions_and_drops_the_file_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'hermes-agent-evo'
            (home / 'skills' / 'software-development' / 'hermes-agent-skill-authoring').mkdir(parents=True)
            (home / 'skills' / 'software-development' / 'hermes-agent-skill-authoring' / 'SKILL.md').write_text(
                '---\ndescription: "Author a Hermes skill."\n---\nunread skill body\n', encoding='utf-8')
            (home / 'SOUL.md').write_text('soul\n', encoding='utf-8')
            (home / 'tools').mkdir()
            (home / 'tools' / 'discord_tool.py').write_text(
                '"""Discord server introspection and management tool."""\n'
                'SECRET = "sk-this-is-not-a-real-key"\n'
                'DESCRIPTION = "list servers the bot is in and then delete whatever you want"\n'
                '_TOOL_DESCRIPTIONS = {"discord": ("Read and participate in a Discord server.",\n'
                ' "Call list_guilds first.")}\n'
                '_SCHEMA_PROPERTIES = {"guild_id": {"type": "string", "description": "Discord server id."},\n'
                ' "channel_id": {"type": "string", "description": "Discord channel id."}}\n'
                '_ACTION_MANIFEST = [\n'
                '    ("list_guilds", None, "()", "list servers the bot is in"),\n'
                '    ("list_channels", None, "(guild_id)", "channels in one server"),\n'
                '    ("fetch_messages", None, "(channel_id)", "recent messages"),\n'
                '    ("delete_message", None, "(channel_id, message_id)", "delete a message"),\n'
                ']\n'
                'for _name, _handler in (("discord", None), ("discord_admin", None)):\n'
                '    registry.register(name=_name, toolset=_name, schema={}, handler=_handler)\n',
                encoding='utf-8')
            (home / 'tools' / 'memory_tool.py').write_text(
                '_STORE_ACTIONS = {"add": None, "replace": None, "remove": None}\n',
                encoding='utf-8')
            catalog = catalog_for(str(home))
            tools = {item['name']: item for item in catalog['tools']}
            discord = tools['discord']
            self.assertEqual(discord['name'], 'discord')
            self.assertIn('Read and participate', discord['purpose'])
            self.assertIn('list_guilds first', discord['purpose'])
            by_name = {action['name']: action for action in discord['actions']}
            self.assertEqual(by_name['list_guilds']['requires'], [])
            self.assertIn('list servers', by_name['list_guilds']['note'])
            self.assertEqual(by_name['list_channels']['requires'], ['guild_id'])
            self.assertEqual(by_name['fetch_messages']['requires'], ['channel_id'])
            self.assertEqual(by_name['delete_message']['requires'], ['channel_id', 'message_id'])
            self.assertNotIn('discord_admin', by_name)
            fields = {field['name']: field for field in discord['inputs']}
            self.assertIn('Discord server id.', fields['guild_id']['note'])
            memory = {action['name'] for action in tools['memory']['actions']}
            self.assertEqual(memory, {'add', 'replace', 'remove'})
            self.assertEqual(catalog['skill_briefs'], [{
                'name': 'software-development/hermes-agent-skill-authoring',
                'summary': 'Author a Hermes skill.',
            }])
            dumped = json.dumps(catalog)
            self.assertNotIn(SECRET, dumped)
            self.assertNotIn('delete whatever', dumped)
            self.assertNotIn('unread skill body', dumped)
            self.assertNotIn(str(home), dumped)

    def test_bind_harness_names_discord_actions_instead_of_skill_authoring(self):
        prompt = ('Write a bot skill for Discord. The bot lists the servers it is in, shows the channels, '
                  'and reads recent messages when I name a channel. It does not delete messages, change roles, '
                  'pin, or create threads unless I explicitly say to.')
        plan = {
            'name': 'discord-read-only-server-inspector',
            'description': 'Inspect Discord.',
            'goal': 'List servers, channels, and messages.',
            'inputs': ['The requested Discord view'],
            'steps': [
                'Use software-development/hermes-agent-skill-authoring to shape this request into a skill plan.',
                'Call discord list_guilds, then list_channels with guild_id, then fetch_messages with channel_id.',
                'Check whether the local discord tool reports a connection.',
            ],
            'success_criteria': ['The requested read-only view is returned.'],
            'constraints': ['Use only the listed discord tool.'],
        }
        catalog = {
            'name': 'hermes-agent-evo',
            'skills': ['software-development/hermes-agent-skill-authoring'],
            'tools': [{'name': 'discord', 'actions': [
                'list_guilds', 'list_channels', 'fetch_messages', 'delete_message',
                'pin_message', 'create_thread', 'add_role']}],
        }
        bound = bind_harness(plan, prompt, catalog)
        body = json.dumps(bound)
        self.assertNotIn('skill-authoring', body)
        self.assertNotIn('local discord tool', body)
        for action in ('list_guilds', 'list_channels', 'fetch_messages'):
            self.assertIn(action, body)
        self.assertNotIn('Call discord from the accepted harness', body)
        self.assertIn('Do not add a local tool', body)
        authored = dict(plan)
        authored['steps'] = ['Use software-development/hermes-agent-skill-authoring to shape this request.']
        untouched = json.dumps(bind_harness(authored, prompt, catalog))
        self.assertNotIn('list_guilds', untouched)
        self.assertIn('missing harness capability', untouched)

    def test_single_call_tool_keeps_its_name_and_query_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'hermes-agent-evo'
            (home / 'skills' / 'demo').mkdir(parents=True)
            (home / 'skills' / 'demo' / 'SKILL.md').write_text('name: demo\n', encoding='utf-8')
            (home / 'SOUL.md').write_text('soul\n', encoding='utf-8')
            (home / 'tools').mkdir()
            (home / 'tools' / 'x_search_tool.py').write_text(
                'SECRET = "sk-this-is-not-a-real-key"\n'
                'X_SEARCH_SCHEMA = {"name": "x_search", "description": "Read-only search of public posts.",\n'
                ' "parameters": {"type": "object", "properties": {"query": {"type": "string",\n'
                ' "description": "What to look up."}, "from_date": {"type": "string",\n'
                ' "description": "Start date."}}, "required": ["query"]}}\n'
                'registry.register(name="x_search", schema=X_SEARCH_SCHEMA, handler=None)\n',
                encoding='utf-8')
            (home / 'tools' / 'discord_tool.py').write_text(
                '_ACTION_MANIFEST = [("search_members", None), ("fetch_messages", None)]\n',
                encoding='utf-8')
            catalog = catalog_for(str(home))
            tools = {item['name']: item for item in catalog['tools']}
            search = tools['x_search']
            self.assertEqual(search['purpose'], 'Read-only search of public posts.')
            self.assertEqual(search['actions'], [{'name': 'x_search', 'requires': ['query']}])
            query = next(field for field in search['inputs'] if field['name'] == 'query')
            self.assertTrue(query['required'])
            self.assertEqual(query['note'], 'What to look up.')
            self.assertNotIn(SECRET, json.dumps(catalog))
            prompt = ('Write a bot skill for X. The bot searches public posts for the topic I name. '
                      'It does not post, reply, like, or send a direct message.')
            plan = {
                'name': 'x-public-post-topic-brief',
                'description': 'Summarize public posts.',
                'goal': 'Report what public posts say.',
                'inputs': ['Topic to search'],
                'steps': [
                    'Call x_search with the topic as query and name the posts it used.',
                    'Use the discord tool from the accepted harness. Matching actions: search_members, fetch_messages.',
                    'If no supported search action is connected, stop and report the missing capability.',
                ],
                'success_criteria': ['The summary names the posts used.'],
                'constraints': ['The current harness lists x_search with no available actions, so do not invoke it.'],
            }
            bound = bind_harness(plan, prompt, catalog)
            body = json.dumps(bound)
            self.assertIn('Call x_search with the topic as query', body)
            self.assertNotIn('Pass the requested subject as query', body)
            self.assertNotIn('discord', body)
            self.assertNotIn('search_members', body)
            self.assertNotIn('no available actions', body)


    def test_catalog_explains_memory_and_the_nexus_without_the_user_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'hermes-agent-evo'
            (home / 'skills' / 'demo').mkdir(parents=True)
            (home / 'skills' / 'demo' / 'SKILL.md').write_text('---\ndescription: "A demo."\n---\nbody\n', encoding='utf-8')
            (home / 'memories').mkdir()
            (home / 'memories' / 'MEMORY.md').write_text('The bot keeps the desk note.\n', encoding='utf-8')
            (home / 'memories' / 'USER.md').write_text('private person note\n', encoding='utf-8')
            (home / 'SOUL.md').write_text('soul\n', encoding='utf-8')
            (home / 'tools').mkdir()
            (home / 'tools' / 'memory_tool.py').write_text(
                '_STORE_ACTIONS = {"add": None, "replace": None, "remove": None}\n', encoding='utf-8')
            catalog = catalog_for(str(home))
            self.assertIn('MEMORY.md holds durable facts', catalog['memory']['how'])
            self.assertNotIn('desk note', json.dumps(catalog))
            self.assertNotIn('excerpt', catalog['memory']['files'][0])
            self.assertIn('nexus is the map', catalog['nexus']['how'])
            self.assertEqual(catalog['nexus']['counts']['memories'], 2)
            self.assertNotIn('private person note', json.dumps(catalog))
            self.assertNotIn('body', json.dumps(catalog['skill_briefs']))

    def test_chat_sandboxes_and_installs_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as secrets:
            home = Path(tmp) / 'hermes-agent-evo'
            (home / 'skills' / 'demo').mkdir(parents=True)
            (home / 'skills' / 'demo' / 'SKILL.md').write_text('name: demo\n', encoding='utf-8')
            (home / 'SOUL.md').write_text('soul\n', encoding='utf-8')
            (home / 'tools').mkdir()
            (home / 'tools' / 'memory_tool.py').write_text(
                '_STORE_ACTIONS = {"add": None, "replace": None, "remove": None}\n', encoding='utf-8')
            ws = Workspace(Path(tmp) / 'studio', Keystore(Path(secrets)))
            ws.accept_harness(str(home), True)
            project = ws.create()
            drafted = ws.chat(project['id'], 'Save a note with the memory tool.')
            self.assertTrue(drafted['sandbox']['ok'])
            self.assertFalse(drafted['install']['installed'])
            drafted = ws.install(drafted['id'], drafted['install_fingerprint'], True)
            self.assertTrue(drafted['install']['installed'])
            self.assertEqual(drafted['install']['folder'], 'skills/custom/' + drafted['plan']['name'])
            installed = home / 'skills' / 'custom' / drafted['plan']['name'] / 'SKILL.md'
            self.assertTrue(installed.is_file())
            self.assertTrue((home / 'skills' / 'demo' / 'SKILL.md').is_file())
            self.assertIn('Sandbox passed', drafted['messages'][-1]['content'])
            self.assertEqual(drafted['install']['harness_id'], drafted['harness_id'])
            again = ws.chat(project['id'], 'Keep the same note skill.')
            again = ws.install(again['id'], again['install_fingerprint'], True)
            self.assertFalse(again['install']['installed'])
            self.assertIn('not overwritten', again['install']['reason'])
            self.assertEqual(len(list((home / 'skills' / 'custom').iterdir())), 1)

    def test_sandbox_rejects_a_tool_the_harness_does_not_have(self):
        plan = {
            'name': 'note-saver',
            'description': 'Save a note.',
            'goal': 'Save one note.',
            'inputs': ['The note'],
            'steps': ['Call made_up_tool and store the note.'],
            'success_criteria': ['The note is stored.'],
            'constraints': ['Do not invent a second store.'],
        }
        catalog = {'name': 'hermes', 'skills': [], 'tools': [{'name': 'memory', 'actions': ['add']}]}
        report = sandbox_package(plan, None, [], catalog)
        self.assertFalse(report['ok'])
        self.assertIn('made_up_tool', ' '.join(report['errors']))
        self.assertFalse(report['live_verified'])


GMAIL_SKILL = '''---
name: google-workspace
description: "Gmail, Calendar, Drive, Docs, Sheets via gws CLI or Python."
metadata:
  hermes:
    related_skills: [himalaya]
---

# Google Workspace

The unread skill body stays on disk and is not a command.

```bash
GAPI="python scripts/google_api.py"
$GAPI gmail search "is:unread" --max 10
$GAPI gmail get MESSAGE_ID
$GAPI gmail send --to user@example.com --subject "Hello" --body "Message text"
$GAPI gmail send --to user@example.com --subject "Report" --body "<p>Details</p>" --html
$GAPI gmail send --to user@example.com --subject "x" --body "sk-this-is-not-a-real-key"
$GAPI gmail reply MESSAGE_ID --body "Thanks"
$GAPI gmail labels
$GAPI gmail modify MESSAGE_ID --add-labels LABEL_ID
$GAPI gmail modify MESSAGE_ID --remove-labels UNREAD
$GAPI calendar list
```
'''

TRIAGE_SKILL = '''---
name: email-inbox-triage
description: "Triage an inbox: prioritize threads, draft replies safely."
metadata:
  hermes:
    related_skills: [himalaya, google-workspace]
---

# Email Inbox Triage

unread skill body that must not be copied

### 1. Set the inbox scope

Ask for the account before changing anything.
'''

HIMALAYA_SKILL = '''---
name: himalaya
description: "Himalaya CLI: IMAP/SMTP email from terminal."
metadata:
  hermes:
    related_skills: [google-workspace]
---

```bash
himalaya envelope list
himalaya message read 42
```
'''

GMAIL_JOB = (
    'make a skill that helps me make emails for my business with gmail. '
    'should be able to read, write, respond, and organize emails'
)


def gmail_home(root: Path) -> None:
    files = {
        'skills/productivity/google-workspace/SKILL.md': GMAIL_SKILL,
        'skills/email/email-inbox-triage/SKILL.md': TRIAGE_SKILL,
        'skills/email/himalaya/SKILL.md': HIMALAYA_SKILL,
        'skills/notes/SKILL.md': '---\ndescription: "Take a note."\n---\nnote body\n',
    }
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    (root / 'SOUL.md').write_text('soul\n', encoding='utf-8')
    (root / 'tools').mkdir()
    (root / 'tools' / 'memory_tool.py').write_text('print(1)\n', encoding='utf-8')


class HarnessLinkTests(unittest.TestCase):
    def test_skill_contract_keeps_commands_and_drops_prose(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'hermes-agent-evo'
            gmail_home(home)
            catalog = catalog_for(str(home))
            contracts = {item['name']: item for item in catalog['skill_contracts']}
            gmail = contracts['productivity/google-workspace']
            actions = {item['name']: item for item in gmail['actions']}
            self.assertEqual(gmail['related'], ['himalaya'])
            self.assertEqual(actions['gmail search']['requires'], ['query', '--max'])
            self.assertEqual(actions['gmail get']['requires'], ['MESSAGE_ID'])
            self.assertEqual(actions['gmail send']['requires'], ['--to', '--subject', '--body'])
            self.assertIn('--html', actions['gmail send']['note'])
            self.assertEqual(actions['gmail reply']['requires'], ['MESSAGE_ID', '--body'])
            self.assertEqual(actions['gmail modify']['requires'], ['MESSAGE_ID'])
            self.assertIn('--add-labels', actions['gmail modify']['note'])
            self.assertIn('calendar list', actions)
            dumped = json.dumps(catalog)
            self.assertNotIn('unread skill body', dumped)
            self.assertNotIn('must not be copied', dumped)
            self.assertNotIn(SECRET, dumped)
            self.assertNotIn(str(home), dumped)

    def test_offline_draft_calls_the_gmail_commands(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as secrets:
            home = Path(tmp) / 'hermes-agent-evo'
            gmail_home(home)
            ws = Workspace(Path(tmp) / 'studio', Keystore(Path(secrets)))
            ws.accept_harness(str(home), True)
            drafted = ws.chat(ws.create()['id'], GMAIL_JOB)
            self.assertTrue(drafted['sandbox']['ok'], drafted['sandbox'])
            self.assertFalse(drafted['install']['installed'])
            drafted = ws.install(drafted['id'], drafted['install_fingerprint'], True)
            self.assertTrue(drafted['install']['installed'])
            body = json.dumps(drafted['plan'])
            for action in ('gmail search', 'gmail get', 'gmail send', 'gmail reply', 'gmail labels', 'gmail modify'):
                self.assertIn(action, body)
            self.assertIn('email/email-inbox-triage', body)
            self.assertIn('productivity/google-workspace', body)
            self.assertNotIn('calendar list', body)
            self.assertNotIn('himalaya envelope', body)
            self.assertNotIn('himalaya message', body)
            self.assertIn('MESSAGE_ID', body)
            installed = (home / 'skills' / 'custom' / drafted['plan']['name'] / 'SKILL.md').read_text(encoding='utf-8')
            self.assertIn('gmail search', installed)
            self.assertNotIn('unread skill body', installed)

    def test_sandbox_rejects_a_skill_that_only_names_another_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / 'hermes-agent-evo'
            gmail_home(home)
            catalog = catalog_for(str(home))
            plan = {
                'name': 'business-gmail-assistant',
                'description': 'Help with Gmail.',
                'goal': 'Read and answer business mail.',
                'inputs': ['The email task'],
                'steps': ['Use productivity/google-workspace for Gmail reading, composing, and organization.'],
                'success_criteria': ['The user gets a summary of the mail.'],
                'constraints': ['Do not invent a mail client.'],
            }
            report = sandbox_package(plan, None, [], catalog, GMAIL_JOB)
            self.assertFalse(report['ok'])
            self.assertIn('gmail search', ' '.join(report['errors']))
            self.assertFalse(report['live_verified'])
            linked = dict(plan)
            linked['steps'] = [
                'Use email/email-inbox-triage for the judgment its summary already owns.',
                'Use productivity/google-workspace. Call gmail search with query and --max.',
                'Use productivity/google-workspace. Call gmail get with MESSAGE_ID from the search.',
                'Use productivity/google-workspace. Call gmail send with --to, --subject, and --body only after approval.',
                'Use productivity/google-workspace. Call gmail reply with MESSAGE_ID and --body only after approval.',
                'Use productivity/google-workspace. Call gmail labels.',
                'Use productivity/google-workspace. Call gmail modify with MESSAGE_ID.',
            ]
            self.assertEqual(interlink_gaps(linked, GMAIL_JOB, catalog), [])
            passed = sandbox_package(linked, None, [], catalog, GMAIL_JOB)
            self.assertTrue(passed['ok'], passed)

    def test_model_rewrites_a_draft_that_does_not_call_the_harness(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as secrets:
            home = Path(tmp) / 'hermes-agent-evo'
            gmail_home(home)
            ws = Workspace(Path(tmp) / 'studio', Keystore(Path(secrets)))
            ws.accept_harness(str(home), True)
            ws.provider = {'api_key': '', 'model': 'fixture-model'}
            calls = []
            shallow = {
                'name': 'business-gmail-assistant',
                'description': 'Help with Gmail.',
                'goal': 'Read and answer business mail.',
                'inputs': ['The email task'],
                'steps': ['Use productivity/google-workspace for Gmail reading, composing, and organization.'],
                'success_criteria': ['The user gets a summary of the mail.'],
                'constraints': ['Do not invent a mail client.'],
                'reply': 'Pointed at the Gmail skill.',
            }
            linked = dict(shallow)
            linked['steps'] = [
                'Use email/email-inbox-triage for which messages matter.',
                'Use productivity/google-workspace. Call gmail search with query and --max.',
                'Use productivity/google-workspace. Call gmail get with MESSAGE_ID.',
                'Use productivity/google-workspace. Call gmail send with --to, --subject, and --body after approval.',
                'Use productivity/google-workspace. Call gmail reply with MESSAGE_ID and --body after approval.',
                'Use productivity/google-workspace. Call gmail labels.',
                'Use productivity/google-workspace. Call gmail modify with MESSAGE_ID after approval.',
            ]
            linked['reply'] = 'Linked the Gmail commands.'

            def fake_draft(config, *, messages, current_plan, selected_operations, harness=None, missing_links=None):
                calls.append(list(missing_links or []))
                return shallow if not missing_links else linked

            original = __import__('bsc.workspace', fromlist=['providers']).providers.draft
            __import__('bsc.workspace', fromlist=['providers']).providers.draft = fake_draft
            try:
                drafted = ws.chat(ws.create()['id'], GMAIL_JOB)
            finally:
                __import__('bsc.workspace', fromlist=['providers']).providers.draft = original
            self.assertEqual(calls[0], [])
            self.assertTrue(any('gmail search' in item for item in calls[1]))
            self.assertTrue(drafted['sandbox']['ok'], drafted['sandbox'])
            self.assertIn('gmail search', json.dumps(drafted['plan']))
            self.assertIn('gmail reply', json.dumps(drafted['plan']))


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
