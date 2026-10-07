"""Local project persistence and algorithm-gated artifact issuance."""
from __future__ import annotations
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
import uuid
from . import core, harness, openapi, providers
from .control import Action, Authority, Controller, Outcome, Skill, ToolRule
from .keystore import PROVIDERS, Keystore, is_ollama_url
from .security import InputError, no_secrets, text


class Workspace:
    def __init__(self, directory: Path, keystore: Keystore | None = None):
        self.path = directory.resolve()
        self.path.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.projects = self.path / 'projects'
        self.projects.mkdir(exist_ok=True, mode=0o700)
        self.exports = self.path / 'exports'
        self.exports.mkdir(exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        self.authority = Authority(secrets.token_bytes(32))
        self.provider = None
        self.keystore = keystore if keystore is not None else Keystore()
        # Only explicit env configuration activates the provider at startup.
        if os.environ.get('BSC_MODEL_BASE_URL') and os.environ.get('BSC_MODEL'):
            self.provider = providers.normalize_config({
                'base_url': os.environ['BSC_MODEL_BASE_URL'], 'model': os.environ['BSC_MODEL'],
                'local': os.environ.get('BSC_MODEL_LOCAL') == '1',
                'json_mode': os.environ.get('BSC_MODEL_JSON', '1') == '1',
                'token_field': os.environ.get('BSC_MODEL_TOKEN_FIELD', 'max_completion_tokens')})
            if self.provider['local'] and is_ollama_url(self.provider['base_url']):
                self.keystore.save_local(self.provider)

    def _path(self, project_id):
        if not isinstance(project_id, str) or not re.fullmatch(r'[0-9a-f]{32}', project_id):
            raise InputError('Invalid project ID.')
        return self.projects / (project_id + '.json')

    def save(self, project):
        target = self._path(project['id'])
        temp = target.with_suffix('.tmp-' + secrets.token_hex(4))
        data = core.pretty(project)
        no_secrets(project)
        if self.provider and self.provider['api_key'] and self.provider['api_key'] in data:
            raise InputError('A configured API credential appeared in project content. It was not saved.')
        with temp.open('x', encoding='utf-8', newline='\n') as handle:
            if os.name != 'nt':
                os.chmod(temp, 0o600)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)

    def get(self, project_id):
        path = self._path(project_id)
        if not path.is_file():
            raise InputError('Project not found.')
        return json.loads(path.read_text(encoding='utf-8'))

    def list(self):
        rows = []
        for path in self.projects.glob('*.json'):
            p = json.loads(path.read_text(encoding='utf-8'))
            plan = p.get('plan') or {}
            rows.append({'id': p['id'], 'name': plan.get('name', 'Untitled skill'),
                         'description': (plan.get('description') or '')[:180],
                         'updated_at': p['updated_at'], 'revision': p['revision']})
        return sorted(rows, key=lambda x: x['updated_at'], reverse=True)

    def delete(self, project_id):
        """Remove one local draft. Issued export archives are left in place."""
        with self.lock:
            path = self._path(project_id)
            if not path.is_file():
                raise InputError('Project not found.')
            path.unlink()
            return {'deleted': project_id}

    def create(self):
        p = {'id': uuid.uuid4().hex, 'revision': 0, 'updated_at': time.time(), 'messages': [],
             'plan': None, 'api': None, 'selected_ids': [], 'draft_source': 'offline_template',
             'tool_generation': False}
        self.save(p)
        return self.view(p)

    def view(self, p):
        p = dict(p)
        files = core.compile_package(p['plan'], p['api'], p['selected_ids'],
                                     tool_generation=p.get('tool_generation') is True) if p['plan'] else {}
        p['files'] = {k: v.decode('utf-8') for k, v in files.items()}
        p['validation'] = core.validate_files(files) if files else None
        p['export_fingerprint'] = core.fingerprint({'id': p['id'], 'revision': p['revision'],
            'files': {k: sha256(v).hexdigest() for k, v in files.items()}})
        p['stages'] = core.STAGES
        return p

    def _update(self, p):
        p['revision'] += 1
        p['updated_at'] = time.time()
        self.save(p)
        return self.view(p)

    def set_tool_generation(self, project_id, enabled):
        if not isinstance(enabled, bool):
            raise InputError('Tool generation must be on or off.')
        with self.lock:
            p = self.get(project_id)
            p['tool_generation'] = enabled
            if p['plan']:
                return self._update(p)
            self.save(p)
            return self.view(p)

    def chat(self, project_id, message, tool_generation=None):
        message = text(message, 'Message', 10000)
        no_secrets(message)
        with self.lock:
            p = self.get(project_id)
            if isinstance(tool_generation, bool):
                p['tool_generation'] = tool_generation
            if len(p['messages']) >= 100:
                raise InputError('This project reached 100 messages. Export or start a new project.')
            if self.provider and self.provider['api_key'] and self.provider['api_key'] in message:
                raise InputError('Use the model settings for credentials, never the chat.')
            ops = [x for x in (p['api'] or {}).get('operations', []) if x['id'] in p['selected_ids']]
            messages = p['messages'] + [{'role': 'user', 'content': message}]
            catalog = self.drafting_harness()
            if self.provider:
                proposal = providers.draft(self.provider, messages=messages, current_plan=p['plan'],
                                           selected_operations=ops, tool_generation=p.get('tool_generation') is True,
                                           harness=catalog)
                plan = core.validate_plan(proposal)
                reply = text(proposal.get('reply', 'Draft updated. Review the contract before export.'), 'Model reply', 1500)
                no_secrets(reply)
                source = 'model:' + self.provider['model']
            else:
                plan = core.offline_plan(message, ops, p['plan'], catalog)
                reply = ('Added your refinement as an explicit constraint. Template mode does not infer a rewritten plan; '
                         'edit the blueprint or connect a model for semantic revisions.' if p['plan'] else
                         'Your brief is now a portable draft with required inputs, a bounded workflow, and evidence checks. '
                         'Review the blueprint, select any API operations, then export. This is deterministic template mode, not an AI model.')
                source = 'offline_template'
            p.update({'messages': messages + [{'role': 'assistant', 'content': reply}], 'plan': plan, 'draft_source': source})
            return self._update(p)

    def import_api(self, project_id, document):
        api = openapi.import_document(document)
        with self.lock:
            p = self.get(project_id)
            p.update({'api': api, 'selected_ids': []})
            return self._update(p)

    def select(self, project_id, selected_ids):
        with self.lock:
            p = self.get(project_id)
            valid = {x['id'] for x in (p['api'] or {}).get('operations', [])}
            if not isinstance(selected_ids, list) or any(not isinstance(x, str) or x not in valid for x in selected_ids):
                raise InputError('Select only operations from the imported API.')
            if len(set(selected_ids)) != len(selected_ids):
                raise InputError('Duplicate operation selection.')
            p['selected_ids'] = selected_ids
            return self._update(p)

    def edit_plan(self, project_id, plan):
        with self.lock:
            p = self.get(project_id)
            p['plan'] = core.validate_plan(plan)
            return self._update(p)

    def provider_info(self):
        if self.provider is None:
            return {'connected': False, 'mode': 'offline_template'}
        return {'connected': True, 'mode': 'model', **{k: self.provider[k] for k in ('model', 'base_url', 'local', 'json_mode', 'token_field')}}

    def secret_status(self):
        """Which providers have a saved key. The key itself is never included."""
        return {'saved_keys': self.keystore.list_providers(), 'local_saved': self.keystore.local_preference()}

    def save_provider_key(self, provider, api_key):
        with self.lock:
            return self.keystore.save(provider, api_key)

    def configure_provider(self, config):
        if not isinstance(config, dict):
            raise InputError('Provider configuration must be an object.')
        config = dict(config)
        provider_id = config.pop('provider_id', None)
        if not isinstance(provider_id, str):
            provider_id = None
        with self.lock:
            if config.get('local') is not True and provider_id in PROVIDERS and not str(config.get('api_key') or '').strip():
                saved = self.keystore.load(provider_id)
                if saved:
                    config['api_key'] = saved
            self.provider = providers.normalize_config(config)
            info = self.provider_info()
            if self.provider['local'] and is_ollama_url(self.provider['base_url']):
                self.keystore.save_local(self.provider)
                info['saved'] = True
                info['local_saved'] = True
                info['confirmation'] = 'Saved for the next session. No API key is used.'
            elif provider_id in PROVIDERS and self.keystore.has(provider_id):
                info['key_saved'] = True
            return info

    def harness_file(self):
        folder = self.path / 'harness'
        folder.mkdir(exist_ok=True, mode=0o700)
        return folder / 'profile.json'

    def drafting_harness(self):
        """The accepted map, read again by name only. Chat text cannot change the path."""
        profile = self.harness_profile()
        path = profile.get('path') if profile.get('accepted') else None
        if not isinstance(path, str):
            return None
        return harness.catalog_for(path)

    def harness_profile(self):
        path = self.path / 'harness' / 'profile.json'
        if not path.is_file():
            return {'accepted': False}
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or data.get('accepted') is not True:
            return {'accepted': False}
        return data

    def find_harness(self, extra=None):
        return harness.find_homes(extra if isinstance(extra, str) and extra.strip() else None)

    def accept_harness(self, path, agreed):
        if agreed is not True:
            raise InputError('Agree that this is the harness, then accept.')
        profile = harness.accept_path(path)
        target = self.harness_file()
        temp = target.with_suffix('.tmp-' + secrets.token_hex(4))
        data = core.pretty(profile)
        no_secrets(profile)
        with self.lock:
            with temp.open('x', encoding='utf-8', newline='\n') as handle:
                if os.name != 'nt':
                    os.chmod(temp, 0o600)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, target)
        return profile

    def remove_harness(self):
        """Drop the accepted map. The harness folder on disk is left alone."""
        target = self.path / 'harness' / 'profile.json'
        with self.lock:
            if target.is_file():
                target.unlink()
        return {'accepted': False}

    def export(self, project_id, expected_fingerprint):
        """The local owner approves exactly the current preview; no business API runs."""
        with self.lock:
            p = self.get(project_id)
            view = self.view(p)
            if not p['plan']:
                raise InputError('Create a draft before exporting.')
            if not secrets.compare_digest(str(expected_fingerprint), view['export_fingerprint']):
                raise InputError('Draft changed after review. Read the current preview and approve it again.')
            if not view['validation']['ok']:
                raise InputError('Static validation failed. Export stopped.')
            source = core.ROOT / 'templates' / 'skill-template.md'
            binding = Skill.from_file(source, name='skill-compiler', version='0.1.0',
                                      objective='export-reviewed-skill', tools=('export_archive',))
            run_id = 'export-' + project_id + '-' + str(p['revision']) + '-' + view['export_fingerprint'][:16]
            target = self.exports / (run_id + '.zip')
            controller = Controller(self.path / 'ledger.sqlite3', skills=[binding],
                tool_rules={'export_archive': ToolRule(True)}, authority=self.authority,
                verifier_ids=frozenset({'archive-roundtrip-v1'}))
            try:
                if not controller.db.execute('SELECT 1 FROM runs WHERE id=?', (run_id,)).fetchone():
                    controller.start(run_id, 'creator-local/0.1.0', max_actions=1, max_units=1, ttl_seconds=300)
                binding.load_unchanged(source)
                action = Action.create(run_id=run_id, step_id='export', skill=binding, tool='export_archive',
                    params={'draft_fingerprint': view['export_fingerprint']}, observed_state=view['export_fingerprint'],
                    verifier_id='archive-roundtrip-v1')
                approval = self.authority.approve(action, time.time() + 60)
                decision = controller.issue(action, live_state=view['export_fingerprint'],
                    available_tools=frozenset({'export_archive'}), approval=approval)
                if decision == 'SUCCESS' and target.is_file():
                    return p['plan']['name'] + '.zip', target.read_bytes()
                if decision != 'DISPATCH':
                    raise InputError('Export is unresolved or its artifact is missing. Review a new draft revision; do not replay it.')
                try:
                    files = {k: v.encode() for k, v in view['files'].items()}
                    raw = core.zip_bytes(p['plan']['name'], files)
                    temp = target.with_suffix('.tmp')
                    temp.write_bytes(raw)
                    os.replace(temp, target)
                    if target.read_bytes() != raw:
                        raise OSError('Archive read-back failed')
                    controller.resolve(self.authority.attest(action, Outcome.SUCCESS, 'sha256:' + sha256(raw).hexdigest()))
                except Exception:
                    controller.resolve(self.authority.attest(action, Outcome.UNKNOWN))
                    raise
                return p['plan']['name'] + '.zip', raw
            finally:
                controller.close()
