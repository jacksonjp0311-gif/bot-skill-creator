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
from .harness_store import HarnessStore
from .control import Action, Authority, Controller, Outcome, Skill, ToolRule
from .keystore import PROVIDERS, Keystore, is_ollama_url
from .security import InputError, no_secrets, text

_ACTIVE = object()


def _with_outcome(reply: str, sandbox: dict, install: dict) -> str:
    notes = []
    if sandbox.get('ok'):
        notes.append('Sandbox passed. The package was checked in a temporary folder. The skill was not run.')
    else:
        detail = '; '.join(sandbox.get('errors') or ['The package check failed.'])
        notes.append('Sandbox stopped the install. ' + detail[:400])
    if install.get('installed'):
        notes.append('Installed into the harness at ' + install['folder'] + '.')
    elif install.get('reason'):
        notes.append(install['reason'])
    note = ' '.join(notes)
    body = reply.strip()
    room = 1500 - len(note) - 1
    if len(body) > room:
        body = body[:max(room, 0)].rstrip()
    combined = (body + '\n' + note).strip() if body else note[:1500]
    return text(combined, 'Model reply', 1500)


class Workspace:
    def __init__(self, directory: Path, keystore: Keystore | None = None):
        self.path = directory.resolve()
        self.path.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.projects = self.path / 'projects'
        self.projects.mkdir(exist_ok=True, mode=0o700)
        self.exports = self.path / 'exports'
        self.exports.mkdir(exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        self.harnesses = HarnessStore(self.path)
        self.phase_lock = threading.Lock()
        self.draft_phase = {'id': '', 'phase': '', 'label': ''}
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

    def list(self, harness_id=_ACTIVE):
        if harness_id is _ACTIVE:
            harness_id = self.harness_profile().get('id')
        rows = []
        for path in self.projects.glob('*.json'):
            p = json.loads(path.read_text(encoding='utf-8'))
            if p.get('harness_id') != harness_id:
                continue
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

    def create(self, harness_id=_ACTIVE):
        if harness_id is _ACTIVE:
            harness_id = self.harness_profile().get('id')
        elif harness_id is not None:
            self.harnesses.get(harness_id)
        p = {'id': uuid.uuid4().hex, 'revision': 0, 'updated_at': time.time(), 'messages': [],
             'plan': None, 'api': None, 'selected_ids': [], 'draft_source': 'offline_template',
             'tool_generation': False, 'harness_id': harness_id, 'snapshot_id': None}
        self.save(p)
        return self.view(p)

    def view(self, p):
        p = dict(p)
        p['tool_generation'] = False
        files = core.compile_package(p['plan'], p['api'], p['selected_ids']) if p['plan'] else {}
        p['files'] = {k: v.decode('utf-8') for k, v in files.items()}
        p['validation'] = core.validate_files(files) if files else None
        p['export_fingerprint'] = core.fingerprint({'id': p['id'], 'revision': p['revision'],
            'files': {k: sha256(v).hexdigest() for k, v in files.items()}})
        p['target'] = self.harnesses.get(p['harness_id'])['profile']['path'] if p.get('harness_id') else None
        p['install_fingerprint'] = core.fingerprint({'export': p['export_fingerprint'], 'harness_id': p.get('harness_id'), 'snapshot_id': p.get('snapshot_id')})
        p['stages'] = core.STAGES
        return p

    def _update(self, p):
        p['revision'] += 1
        p['updated_at'] = time.time()
        self.save(p)
        return self.view(p)

    def set_phase(self, project_id, phase):
        labels = {
            'analyzing': 'Analyzing harness',
            'writing': 'Writing the skill',
            'linking': 'Linking the skill to the harness',
            'testing': 'Testing in the sandbox',
            'installing': 'Installing into the harness',
        }
        with self.phase_lock:
            self.draft_phase = {'id': project_id, 'phase': phase, 'label': labels.get(phase, '')}

    def clear_phase(self, project_id):
        with self.phase_lock:
            if self.draft_phase.get('id') == project_id:
                self.draft_phase = {'id': '', 'phase': '', 'label': ''}

    def draft_status(self, project_id):
        with self.phase_lock:
            current = dict(self.draft_phase)
        if not isinstance(project_id, str) or current.get('id') != project_id:
            return {'phase': '', 'label': ''}
        return {'phase': current.get('phase') or '', 'label': current.get('label') or ''}

    def chat(self, project_id, message, tool_generation=None):
        del tool_generation
        message = text(message, 'Message', 10000)
        no_secrets(message)
        self.set_phase(project_id, 'analyzing')
        try:
            with self.lock:
                p = self.get(project_id)
                record = self.harnesses.refresh(p['harness_id']) if p.get('harness_id') else None
                catalog = self.harnesses.drafting_catalog(record) if record else None
                p['snapshot_id'] = record['snapshot']['id'] if record else None
                p['tool_generation'] = False
                if len(p['messages']) >= 100:
                    raise InputError('This project reached 100 messages. Export or start a new project.')
                if self.provider and self.provider['api_key'] and self.provider['api_key'] in message:
                    raise InputError('Use the model settings for credentials, never the chat.')
                ops = [x for x in (p['api'] or {}).get('operations', []) if x['id'] in p['selected_ids']]
                messages = p['messages'] + [{'role': 'user', 'content': message}]
                self.set_phase(project_id, 'writing')
                if self.provider:
                    proposal = providers.draft(self.provider, messages=messages, current_plan=p['plan'],
                                               selected_operations=ops, harness=catalog)
                    plan = core.validate_plan(proposal)
                    reply = text(proposal.get('reply', 'Draft updated. Review the contract before export.'), 'Model reply', 1200)
                    no_secrets(reply)
                    source = 'model:' + self.provider['model']
                    gaps = (core.interlink_gaps(plan, message, catalog) + core.contracts.errors(plan, catalog)) if catalog else []
                    if gaps:
                        self.set_phase(project_id, 'linking')
                        try:
                            revised = providers.draft(
                                self.provider, messages=messages, current_plan=plan,
                                selected_operations=ops, harness=catalog, missing_links=gaps)
                            plan = core.validate_plan(revised)
                            reply = text(revised.get('reply', reply), 'Model reply', 1200)
                            no_secrets(reply)
                        except InputError:
                            pass
                else:
                    plan = core.offline_plan(message, ops, p['plan'], catalog)
                    reply = ('Added your refinement as an explicit constraint. Template mode does not infer a rewritten plan; '
                             'edit the blueprint or connect a model for semantic revisions.' if p['plan'] else
                             'Your brief is now a portable draft with required inputs, a bounded workflow, and evidence checks. '
                             'Review the blueprint, select any API operations, then export. This is deterministic template mode, not an AI model.')
                    source = 'offline_template'
                plan = core.validate_plan(core.bind_harness(plan, message, catalog))
                self.set_phase(project_id, 'testing')
                try:
                    sandbox = core.sandbox_package(plan, p['api'], p['selected_ids'], catalog, message)
                except InputError as exc:
                    sandbox = {'ok': False, 'errors': [str(exc)], 'live_verified': False}
                install = {'installed': False, 'reason': 'Review this revision and approve installation separately.' if catalog else 'No harness is bound, so the skill stayed in the studio.'}
                if record:
                    self.harnesses.remember(record['id'], p['snapshot_id'], project_id, p['revision'] + 1, sandbox)
                reply = _with_outcome(reply, sandbox, install)
                p.update({'messages': messages + [{'role': 'assistant', 'content': reply}], 'plan': plan,
                          'draft_source': source, 'sandbox': sandbox, 'install': install})
                return self._update(p)
        finally:
            self.clear_phase(project_id)

    def _install_into_harness(self, profile, plan, api, selected_ids):
        """Copy a sandbox-checked package into the accepted harness. Never overwrite."""
        path = profile.get('path') if profile.get('accepted') else None
        if not isinstance(path, str):
            return {'installed': False, 'reason': 'No harness is accepted, so the skill stayed in the studio.'}
        try:
            root = harness._verified_root(path)
        except InputError:
            return {'installed': False, 'reason': 'The accepted harness folder is no longer available.'}
        if root != Path(path):
            raise InputError('The bound harness location changed. Reconnect it explicitly.')
        slug = plan['name']
        skills_root = (root / 'skills').resolve()
        if not skills_root.is_relative_to(root) or (root / 'skills').is_symlink():
            raise InputError('The skills directory must stay inside the bound harness.')
        destination = (skills_root / 'custom' / slug).resolve()
        try:
            inside = os.path.commonpath([os.path.normcase(str(skills_root)), os.path.normcase(str(destination))])
        except ValueError:
            inside = ''
        if inside != os.path.normcase(str(skills_root)):
            return {'installed': False, 'reason': 'The install path left the harness skills folder.'}
        if destination.exists() or destination.is_symlink():
            return {'installed': False, 'reason': 'That skill is already in the harness. It was not overwritten.'}
        try:
            core.write_package(skills_root / 'custom', plan, api, selected_ids)
        except (InputError, OSError):
            return {'installed': False, 'reason': 'The skill was not installed. The harness copy was left unchanged.'}
        return {'installed': True, 'folder': 'skills/custom/' + slug}

    def install(self, project_id, expected_fingerprint, approved):
        with self.lock:
            p = self.get(project_id)
            if approved is not True or not p.get('plan') or not p.get('harness_id'):
                raise InputError('Review a harness-bound draft and explicitly approve installation.')
            view = self.view(p)
            if not secrets.compare_digest(str(expected_fingerprint), view['install_fingerprint']):
                raise InputError('Draft or target changed after review. Review it again.')
            record = self.harnesses.refresh(p['harness_id'])
            if record['snapshot']['id'] != p.get('snapshot_id'):
                raise InputError('Harness capabilities changed. Validate the draft again before review.')
            report = core.sandbox_package(p['plan'], p['api'], p['selected_ids'], record['snapshot']['catalog'])
            if not report['ok']:
                raise InputError('Harness validation failed: ' + '; '.join(report['errors']))
            receipt = self._install_into_harness(record['profile'], p['plan'], p['api'], p['selected_ids'])
            receipt.update({'harness_id': p['harness_id'], 'snapshot_id': p['snapshot_id'],
                            'revision': p['revision'], 'fingerprint': expected_fingerprint})
            p['install'] = receipt
            self.save(p)
            return self.view(p)

    def validate(self, project_id):
        with self.lock:
            p = self.get(project_id)
            if not p.get('plan'):
                raise InputError('Create a draft first.')
            record = self.harnesses.refresh(p['harness_id']) if p.get('harness_id') else None
            p['snapshot_id'] = record['snapshot']['id'] if record else None
            p['sandbox'] = core.sandbox_package(p['plan'], p['api'], p['selected_ids'], record['snapshot']['catalog'] if record else None)
            p['install'] = {'installed': False}
            if record:
                self.harnesses.remember(record['id'], p['snapshot_id'], project_id, p['revision'] + 1, p['sandbox'])
            return self._update(p)

    def import_api(self, project_id, document):
        api = openapi.import_document(document)
        with self.lock:
            p = self.get(project_id)
            p.update({'api': api, 'selected_ids': [], 'sandbox': None, 'install': None, 'snapshot_id': None})
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
            p.update({'sandbox': None, 'install': None, 'snapshot_id': None})
            return self._update(p)

    def edit_plan(self, project_id, plan):
        with self.lock:
            p = self.get(project_id)
            p['plan'] = core.validate_plan(plan)
            p.update({'sandbox': None, 'install': None, 'snapshot_id': None})
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
        """The accepted harness, read again. Chat text cannot change the path."""
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
        if not data.get('id'):
            record = self.harnesses.connect(data['path'])
            data = {**record['profile'], 'id': record['id']}
            self.harness_file().write_text(core.pretty(data), encoding='utf-8')
        return data

    def find_harness(self, extra=None):
        return harness.find_homes(extra if isinstance(extra, str) and extra.strip() else None)

    def accept_harness(self, path, agreed):
        if agreed is not True:
            raise InputError('Agree that this is the harness, then accept.')
        with self.lock:
            record = self.harnesses.connect(path)
        profile = {**record['profile'], 'id': record['id']}
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

    def harness_list(self):
        with self.lock:
            active = self.harness_profile().get('id')
            return {'active_id': active, 'harnesses': [
                {'id': r['id'], 'name': Path(r['profile']['path']).name, 'path': r['profile']['path'],
                 'context': r['context'], 'snapshot_id': r['snapshot']['id'],
                 'inspected_at': r['snapshot']['inspected_at'], 'evidence_count': len(r['evidence']),
                 'live_verified': False} for r in self.harnesses.all()]}

    def switch_harness(self, identity):
        with self.lock:
            if identity is None:
                return self.remove_harness()
            record = self.harnesses.get(identity)
            profile = {**record['profile'], 'id': identity}
            self.harness_file().write_text(core.pretty(profile), encoding='utf-8')
            return profile

    def set_harness_context(self, identity, value):
        with self.lock:
            self.harnesses.context(identity, value)
            return self.harness_list()

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
            if p.get('harness_id'):
                record = self.harnesses.refresh(p['harness_id'])
                if record['snapshot']['id'] != p.get('snapshot_id'):
                    raise InputError('Harness capabilities changed or the draft is unvalidated. Validate and review again.')
                report = core.sandbox_package(p['plan'], p['api'], p['selected_ids'], record['snapshot']['catalog'])
                if not report['ok']:
                    raise InputError('Harness validation failed: ' + '; '.join(report['errors']))
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
