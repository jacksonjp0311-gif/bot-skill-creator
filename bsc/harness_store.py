"""Persistent creator context, separate from the harness's own memory."""
import json
import os
import re
import secrets
import time
from pathlib import Path
from . import core, harness
from .security import InputError, no_secrets, text


class HarnessStore:
    def __init__(self, workspace):
        self.path = workspace / 'harnesses'
        self.path.mkdir(exist_ok=True, mode=0o700)

    def file(self, identity):
        if not isinstance(identity, str) or not re.fullmatch(r'[a-f0-9]{32}', identity):
            raise InputError('Invalid harness identity.')
        return self.path / (identity + '.json')

    def get(self, identity):
        path = self.file(identity)
        if not path.is_file():
            raise InputError('Harness workspace is unavailable. Reconnect its original location.')
        return json.loads(path.read_text(encoding='utf-8'))

    def save(self, record):
        no_secrets(record)
        target = self.file(record['id'])
        temp = target.with_suffix('.tmp-' + secrets.token_hex(4))
        with temp.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(core.pretty(record))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, target)

    def all(self):
        return [json.loads(p.read_text(encoding='utf-8')) for p in sorted(self.path.glob('*.json'))]

    def connect(self, path):
        profile = harness.accept_path(path)
        canonical = os.path.normcase(str(Path(profile['path']).resolve()))
        identity = core.fingerprint({'adapter': 'hermes-local-v1', 'path': canonical})[:32]
        record = self.get(identity) if self.file(identity).exists() else {
            'id': identity, 'context': '', 'evidence': [], 'snapshot': None}
        record.update({'profile': profile, 'adapter': 'hermes-local-v1', 'execution_surface': 'local-files-static'})
        self.save(record)
        return self.refresh(identity)

    def refresh(self, identity):
        record = self.get(identity)
        path = Path(record['profile']['path'])
        if not path.is_dir() or path.resolve() != path or harness._verified_root(str(path)) != path:
            raise InputError('The bound harness location changed. Reconnect it explicitly.')
        catalog = harness.catalog_for(str(path))
        if catalog is None:
            raise InputError('The bound harness is unavailable. No other harness was substituted.')
        # Generated skills do not recursively become evidence for future generated skills.
        catalog['skills'] = [x for x in catalog.get('skills', []) if isinstance(x, str) and not x.startswith('custom/')]
        for key in ('skill_contracts', 'skill_briefs'):
            catalog[key] = [x for x in catalog.get(key, []) if isinstance(x, dict) and not str(x.get('name', '')).startswith('custom/')]
        tool_names = [item if isinstance(item, str) else item.get('name', '') for item in catalog.get('tools') or []]
        memories = [item for item in catalog.get('memory_files') or [] if isinstance(item, str)]
        catalog['nexus'] = harness._nexus_understanding(
            path, catalog['skills'], [name for name in tool_names if isinstance(name, str) and name], memories)
        record['snapshot'] = {'id': core.fingerprint(catalog), 'inspected_at': time.time(),
                              'source': 'read-only local files', 'live_verified': False, 'catalog': catalog}
        self.save(record)
        return record

    def remember(self, identity, snapshot_id, project_id, revision, report):
        record = self.get(identity)
        record['evidence'] = (record['evidence'] + [{
            'snapshot_id': snapshot_id, 'project_id': project_id, 'revision': revision,
            'at': time.time(), 'kind': 'static_validation', 'ok': report['ok'],
            'errors': report.get('errors', [])[:12], 'live_verified': False}])[-40:]
        self.save(record)

    def context(self, identity, value):
        record = self.get(identity)
        record['context'] = text(value, 'Harness context', 4000) if value else ''
        self.save(record)
        return record

    def drafting_catalog(self, record):
        catalog = dict(record['snapshot']['catalog'])
        catalog['creator_context'] = record['context']
        catalog['previous_checks'] = [
            {'ok': x['ok'], 'errors': x['errors'], 'kind': x['kind']}
            for x in record['evidence'] if x['snapshot_id'] == record['snapshot']['id']][-5:]
        return catalog
