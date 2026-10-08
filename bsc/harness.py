"""Read-only map of one Hermes home. Nothing here starts Hermes or reads secrets."""
from __future__ import annotations
from datetime import datetime, timezone
from hashlib import sha256
import ast
import os
from pathlib import Path
import re
import shlex

from .security import SECRET_PATTERNS, InputError, no_secrets

MARKERS = ('config.yaml', '.env', 'state.db')
SKIP_DIRS = {
    '.git', '.hg', '.svn', '__pycache__', 'node_modules', 'models', 'runtimes',
    'node', '.venv', 'venv', 'dist', '.deleted', '.cache',
}
SECRET_NAME = re.compile(r'(?i)(api[_-]?key|secret|password|token|credential|authorization|\.env$)')
IDENT = re.compile(r'^[A-Za-z0-9_.:/-]{1,80}$')
ACTION_NAME = re.compile(r'^[a-z][a-z0-9_]{1,48}$')
MAX_SKILLS = 80
MAX_TOOLS = 40
MAX_ACTIONS = 24
MAX_INPUTS = 12
MAX_PURPOSE = 420
MAX_NOTE = 160
MAX_INPUT_NOTE = 140
MAX_TOOL_SOURCE = 800_000
MAX_SKILL_ACTIONS = 16
SHELL_FENCES = {'', 'bash', 'sh', 'shell', 'console', 'zsh', 'powershell', 'ps1'}
SKIP_BINS = {
    'brew', 'cargo', 'curl', 'sudo', 'cd', 'echo', 'cat', 'sed', 'npm', 'pip', 'pip3',
    'git', 'apt', 'winget', 'bash', 'sh', 'python', 'python3', 'py', 'install',
}
SECRET_LINE = ('http://', 'https://', 'client-secret', 'client_secret', 'password', 'access_token',
               'api_key', 'auth-code', 'authorization', 'begin private')
SIGNATURE = re.compile(
    r'^\(\s*([A-Za-z_][A-Za-z0-9_]*(?:\s*,\s*[A-Za-z_][A-Za-z0-9_]*)*)?\s*\)$'
)


def default_roots() -> list[Path]:
    """Homes Hermes itself uses, plus a Hermes folder sitting on the Desktop."""
    roots = []
    local = os.environ.get('LOCALAPPDATA', '').strip()
    if local:
        roots.append(Path(local) / 'hermes')
    roots.append(Path.home() / '.hermes')
    roots.extend(desktop_hermes_dirs())
    return roots


def desktop_dirs() -> list[Path]:
    found = [Path.home() / 'Desktop', Path.home() / 'OneDrive' / 'Desktop']
    one_drive = os.environ.get('OneDrive', '').strip()
    if one_drive:
        found.append(Path(one_drive) / 'Desktop')
    unique = []
    seen = set()
    for path in found:
        key = os.path.normcase(str(path))
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def desktop_hermes_dirs(desks: list[Path] | None = None) -> list[Path]:
    """One level on the Desktop. Only folders whose names say Hermes."""
    found = []
    for desk in desks if desks is not None else desktop_dirs():
        try:
            if not desk.is_dir():
                continue
            children = list(desk.iterdir())
        except OSError:
            continue
        for child in children:
            if child.is_dir() and 'hermes' in child.name.lower():
                found.append(child)
    return found


def find_homes(extra: str | None = None, roots: list[Path] | None = None, desks: list[Path] | None = None) -> dict:
    """Candidate homes only. No profile is saved."""
    ordered = list(default_roots() if roots is None else roots)
    if desks is not None:
        ordered.extend(desktop_hermes_dirs(desks))
    seen: set[str] = set()
    homes = []
    for candidate in ordered:
        info = inspect_candidate(candidate)
        if info is None or info['path'] in seen:
            continue
        seen.add(info['path'])
        homes.append(info)
    if extra:
        info = locate(_typed_path(extra))
        if info is not None and info['path'] not in seen:
            homes.append(info)
    homes.sort(key=lambda item: (item['skill_count'] + item['tool_count'], item['name'].lower()), reverse=True)
    return {'homes': homes}


def catalog_for(path: str) -> dict | None:
    """Fresh tool contracts, skill links, memory, and nexus.

    Skill prose and tool source stay out. A skill contributes its summary,
    the skills it names, and the commands or headings it actually documents.
    """
    try:
        root = _verified_root(path)
    except InputError:
        return None
    tool_names, _sections = _tool_names(root)
    skills = _skill_names(root)
    memories = _memory_names(root)
    catalog = {
        'name': root.name,
        'skills': skills,
        'skill_briefs': _skill_briefs(root),
        'skill_contracts': _skill_contracts(root),
        'tools': _tools_with_actions(root, tool_names),
        'memory_files': memories,
        'memory': _memory_understanding(root, memories),
        'nexus': _nexus_understanding(root, skills, tool_names, memories),
    }
    no_secrets(catalog)
    return catalog


def accept_path(path: str) -> dict:
    """Scan one folder the person already agreed is the harness."""
    root = _verified_root(path)
    profile = _scan(root)
    profile['agreed'] = True
    profile['accepted'] = True
    profile['accepted_at'] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    no_secrets(profile)
    return profile


def inspect_candidate(path: Path) -> dict | None:
    try:
        root = path.expanduser().resolve()
    except OSError:
        return None
    if not root.is_dir() or not _looks_like_hermes(root):
        return None
    markers = _signals(root)
    skills = _skill_names(root)
    memories = _memory_names(root)
    tools, _sections = _tool_names(root)
    return {
        'path': str(root),
        'name': root.name,
        'markers': markers,
        'skill_count': len(skills),
        'memory_files': memories,
        'tool_count': len(tools),
    }


def _typed_path(value: object) -> Path:
    if not isinstance(value, str):
        raise InputError('Enter a folder path.')
    cleaned = value.strip().strip('"').strip("'").strip()
    if cleaned.lower().startswith('file:///'):
        cleaned = cleaned[8:]
    if not cleaned or len(cleaned) > 500 or '\x00' in cleaned:
        raise InputError('Enter a folder path.')
    return Path(cleaned)


def locate(path: Path) -> dict | None:
    """The folder itself, or a Hermes root a few levels above a file or subfolder."""
    try:
        current = path.expanduser()
        if current.exists() and current.is_file():
            current = current.parent
    except OSError:
        return None
    for _step in range(5):
        info = inspect_candidate(current)
        if info is not None:
            return info
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def _verified_root(path: str) -> Path:
    info = locate(_typed_path(path))
    if info is None:
        raise InputError('That folder does not look like Hermes. Choose the folder that contains its skills.')
    return Path(info['path'])


def _scan(root: Path) -> dict:
    skills = _skill_names(root)
    memories = _memory_names(root)
    tools, sections = _tool_names(root)
    shown_skills = _with_more(skills, 40)
    shown_tools = _with_more(tools, 20)
    directory = {
        'name': root.name,
        'kind': 'dir',
        'children': [
            {'name': 'skills', 'kind': 'dir', 'children': [{'name': name, 'kind': 'skill'} for name in shown_skills]},
            {'name': 'memories', 'kind': 'dir', 'children': [{'name': name, 'kind': 'memory'} for name in memories]},
            {'name': 'tools', 'kind': 'dir', 'children': [{'name': name, 'kind': 'tool'} for name in shown_tools]},
            {'name': 'config', 'kind': 'dir', 'children': [{'name': name, 'kind': 'section'} for name in sections]},
        ],
    }
    nodes = [{'id': 'harness', 'kind': 'harness', 'label': root.name}]
    edges = []
    for index, name in enumerate(_nexus_labels(skills)):
        node_id = f'skill-{index}'
        nodes.append({'id': node_id, 'kind': 'skill', 'label': name})
        edges.append({'source': 'harness', 'target': node_id})
    for index, name in enumerate(memories):
        node_id = f'memory-{index}'
        nodes.append({'id': node_id, 'kind': 'memory', 'label': name})
        edges.append({'source': 'harness', 'target': node_id})
    for index, name in enumerate(tools[:8]):
        node_id = f'tool-{index}'
        nodes.append({'id': node_id, 'kind': 'tool', 'label': name})
        edges.append({'source': 'harness', 'target': node_id})
    for node_id, label in (
        ('limit-secrets', 'Secrets stay out'),
        ('limit-network', 'No network on this scan'),
    ):
        nodes.append({'id': node_id, 'kind': 'limit', 'label': label})
        edges.append({'source': 'harness', 'target': node_id})
    listed = [f'skills/{name}' for name in skills]
    listed += [f'memories/{name}' for name in memories]
    listed += [f'tools/{name}' for name in tools]
    listed += [f'config/{name}' for name in sections]
    markers = _signals(root)
    profile = {
        'path': str(root),
        'hash': sha256('\n'.join(sorted(listed + markers)).encode()).hexdigest(),
        'markers': markers,
        'counts': {'skills': len(skills), 'memories': len(memories), 'tools': len(tools)},
        'nexus': {'nodes': nodes, 'edges': edges},
        'directory': directory,
        'restrictions': [
            'Secrets were not loaded.',
            'This scan did not use the network.',
        ],
    }
    no_secrets(profile)
    return profile


def _signals(root: Path) -> list[str]:
    found = []
    for name in MARKERS:
        if (root / name).is_file():
            found.append(name)
    if (root / 'SOUL.md').is_file():
        found.append('SOUL.md')
    for name in ('skills', 'tools', 'memories'):
        if (root / name).is_dir():
            found.append(name)
    return found


def _looks_like_hermes(root: Path) -> bool:
    signals = set(_signals(root))
    if signals & set(MARKERS):
        return True
    if 'SOUL.md' in signals and signals & {'skills', 'tools', 'memories'}:
        return True
    return 'skills' in signals and 'tools' in signals


def _with_more(names: list[str], limit: int) -> list[str]:
    if len(names) <= limit:
        return names
    hidden = len(names) - limit
    return names[:limit] + [f'+ {hidden} more']


def _nexus_labels(skills: list[str]) -> list[str]:
    if len(skills) <= 8:
        return skills
    categories = []
    for name in skills:
        category = name.split('/', 1)[0]
        if category not in categories:
            categories.append(category)
        if len(categories) >= 8:
            break
    return categories


def _tool_names(root: Path) -> tuple[list[str], list[str]]:
    listed, sections = _config_outline(root / 'config.yaml')
    if listed:
        return listed, sections
    folder = root / 'tools'
    if not folder.is_dir():
        return [], sections
    names = []
    try:
        files = sorted(folder.glob('*_tool.py'))
    except OSError:
        return [], sections
    for path in files:
        stem = path.name[:-3]
        if stem.endswith('_tool'):
            stem = stem[:-5]
        if stem and stem not in names and not SECRET_NAME.search(stem):
            names.append(stem)
        if len(names) >= MAX_TOOLS:
            break
    return names, sections


def _tools_with_actions(root: Path, names: list[str]) -> list[dict]:
    """The contract a drafter can learn: purpose, actions, required inputs. Source is not kept."""
    folder = root / 'tools'
    entries = []
    for name in names:
        if not isinstance(name, str) or name.startswith('+ '):
            continue
        entries.append(_tool_contract(folder / f'{name}_tool.py', name))
        if len(entries) >= MAX_TOOLS:
            break
    return entries


def _tool_contract(path: Path, tool_name: str) -> dict:
    blank = {'name': tool_name, 'actions': [], 'inspection': 'contract unavailable'}
    try:
        if not path.is_file() or path.stat().st_size > MAX_TOOL_SOURCE:
            return blank
        tree = ast.parse(path.read_text(encoding='utf-8', errors='replace'))
    except (OSError, SyntaxError, UnicodeError):
        return blank
    actions = _action_records(tree)
    inputs, required, enum_actions = _input_contract(tree, tool_name)
    for action_name in enum_actions:
        _add_action(actions, {'name': action_name, 'requires': []})
    if not actions:
        for action_name in _registered_names(tree):
            _add_action(actions, {'name': action_name, 'requires': []})
    if not actions and _matching_schema(tree, tool_name) is not None:
        actions = [{'name': tool_name, 'requires': [field for field in required if field != 'action'][:6]}]
    else:
        for action in actions:
            if action['name'] == tool_name and not action.get('requires'):
                action['requires'] = [field for field in required if field != 'action'][:6]
    entry = {'name': tool_name, 'actions': [_action_packet(action) for action in actions[:MAX_ACTIONS]]}
    purpose = _purpose(tree, tool_name)
    if purpose:
        entry['purpose'] = purpose
    if inputs:
        entry['inputs'] = inputs[:MAX_INPUTS]
    return entry


def _keep_identifier(value: object) -> bool:
    return isinstance(value, str) and bool(ACTION_NAME.fullmatch(value)) and not SECRET_NAME.search(value)


def _clip(value: str, limit: int) -> str:
    collapsed = ' '.join(value.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit - 1].rstrip() + '…'


def _safe_prose(value: object, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        return ''
    clipped = _clip(value, limit)
    if any(re.search(pattern, clipped) for pattern in SECRET_PATTERNS):
        return ''
    return clipped


def _plain_strings(node: ast.AST | None) -> list[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.Tuple, ast.List)):
        parts = []
        for elt in node.elts:
            parts.extend(_plain_strings(elt))
        return parts
    return []


def _plain_text(node: ast.AST | None) -> str:
    return ' '.join(part.strip() for part in _plain_strings(node) if part.strip())


def _requires(signature: str) -> list[str] | None:
    match = SIGNATURE.fullmatch(signature.strip())
    if not match:
        return None
    body = match.group(1) or ''
    return [part.strip() for part in body.split(',') if part.strip()]


def _record_from_parts(parts: list[str]) -> dict | None:
    name = ''
    requires: list[str] = []
    note = ''
    saw_signature = False
    for part in parts:
        parsed = _requires(part) if part.strip().startswith('(') else None
        if parsed is not None and not saw_signature:
            requires = parsed[:6]
            saw_signature = True
            continue
        if not name and _keep_identifier(part):
            name = part
            continue
        if not note:
            note = _safe_prose(part, MAX_NOTE)
    if not name:
        return None
    record = {'name': name, 'requires': requires}
    if note:
        record['note'] = note
    return record


def _add_action(found: list[dict], record: dict | None) -> None:
    if not record or not _keep_identifier(record.get('name')):
        return
    if any(item['name'] == record['name'] for item in found) or len(found) >= MAX_ACTIONS:
        return
    found.append(record)


def _records_from_node(node: ast.AST) -> list[dict]:
    if isinstance(node, ast.Call):
        records = []
        for arg in node.args:
            records.extend(_records_from_node(arg))
        return records
    if isinstance(node, ast.Dict):
        records = []
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                record = _record_from_parts([key.value, *_plain_strings(value)])
                if record:
                    records.append(record)
        return records
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        records = []
        for elt in node.elts:
            record = _record_from_parts(_plain_strings(elt))
            if record:
                records.append(record)
        return records
    return []


def _module_assignments(tree: ast.AST):
    for node in tree.body:
        names = []
        value = None
        if isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
            value = node.value
        if value is not None:
            for name in names:
                yield name, value


def _registers(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return isinstance(func, ast.Attribute) and func.attr == 'register'


def _action_records(tree: ast.AST) -> list[dict]:
    found: list[dict] = []
    for name, value in _module_assignments(tree):
        if 'action' not in name.lower():
            continue
        for record in _records_from_node(value):
            _add_action(found, record)
    return found


def _registered_names(tree: ast.AST) -> list[str]:
    found: list[str] = []
    for node in ast.walk(tree):
        if _registers(node):
            for keyword in node.keywords:
                if keyword.arg == 'name' and _keep_identifier(getattr(keyword.value, 'value', None)):
                    if keyword.value.value not in found:
                        found.append(keyword.value.value)
        if isinstance(node, ast.For) and any(_registers(child) for child in ast.walk(node)):
            for record in _records_from_node(node.iter):
                if record['name'] not in found:
                    found.append(record['name'])
        if len(found) >= MAX_ACTIONS:
            break
    return found


def _dict_items(node: ast.AST):
    if not isinstance(node, ast.Dict):
        return
    for key, value in zip(node.keys, node.values):
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            yield key.value, value


def _schemas(tree: ast.AST) -> list[dict]:
    found = []
    for _name, value in _module_assignments(tree):
        if not isinstance(value, ast.Dict):
            continue
        fields = dict(_dict_items(value))
        if isinstance(fields.get('parameters'), ast.Dict):
            found.append(fields)
    return found


def _matching_schema(tree: ast.AST, tool_name: str) -> dict | None:
    schemas = _schemas(tree)
    for fields in schemas:
        schema_name = fields.get('name')
        if isinstance(schema_name, ast.Constant) and schema_name.value == tool_name:
            return fields
    if len(schemas) == 1:
        return schemas[0]
    return None


def _enum_names(node: ast.AST) -> list[str]:
    if not isinstance(node, ast.Dict):
        return []
    enum = dict(_dict_items(node)).get('enum')
    names = []
    if isinstance(enum, (ast.List, ast.Tuple)):
        for elt in enum.elts:
            if isinstance(elt, ast.Constant) and _keep_identifier(elt.value):
                names.append(elt.value)
    return names


def _property_inputs(properties: ast.AST, required: set[str]) -> tuple[list[dict], list[str]]:
    inputs = []
    enum_actions = []
    if not isinstance(properties, ast.Dict):
        return inputs, enum_actions
    for field_name, field in _dict_items(properties):
        if field_name == 'action':
            enum_actions.extend(_enum_names(field))
            continue
        if not _keep_identifier(field_name) or len(inputs) >= MAX_INPUTS:
            continue
        packet = {'name': field_name, 'required': field_name in required}
        note = ''
        if isinstance(field, ast.Dict):
            note = _safe_prose(_plain_text(dict(_dict_items(field)).get('description')), MAX_INPUT_NOTE)
        if note:
            packet['note'] = note
        inputs.append(packet)
    return inputs, enum_actions


def _required_names(parameters: ast.AST) -> list[str]:
    if not isinstance(parameters, ast.Dict):
        return []
    required = dict(_dict_items(parameters)).get('required')
    names = []
    if isinstance(required, (ast.List, ast.Tuple)):
        for elt in required.elts:
            if isinstance(elt, ast.Constant) and _keep_identifier(elt.value):
                names.append(elt.value)
    return names


def _input_contract(tree: ast.AST, tool_name: str) -> tuple[list[dict], list[str], list[str]]:
    inputs: list[dict] = []
    seen: set[str] = set()
    required: list[str] = []
    enum_actions: list[str] = []
    schema = _matching_schema(tree, tool_name)
    if schema is not None:
        parameters = schema.get('parameters')
        required = _required_names(parameters)
        properties = dict(_dict_items(parameters)).get('properties') if isinstance(parameters, ast.Dict) else None
        parsed, enum_actions = _property_inputs(properties, set(required))
        for packet in parsed:
            inputs.append(packet)
            seen.add(packet['name'])
    for assign_name, value in _module_assignments(tree):
        if 'propert' not in assign_name.lower() or not isinstance(value, ast.Dict):
            continue
        if isinstance(dict(_dict_items(value)).get('parameters'), ast.Dict):
            continue
        parsed, extra_enum = _property_inputs(value, set())
        enum_actions.extend(extra_enum)
        for packet in parsed:
            if packet['name'] in seen or len(inputs) >= MAX_INPUTS:
                continue
            inputs.append(packet)
            seen.add(packet['name'])
    return inputs, required, enum_actions


def _purpose(tree: ast.AST, tool_name: str) -> str:
    schema = _matching_schema(tree, tool_name)
    if schema is not None:
        prose = _safe_prose(_plain_text(schema.get('description')), MAX_PURPOSE)
        if prose:
            return prose
    for assign_name, value in _module_assignments(tree):
        if 'description' not in assign_name.lower() or not isinstance(value, ast.Dict):
            continue
        for key, item in _dict_items(value):
            if key == tool_name:
                prose = _safe_prose(_plain_text(item), MAX_PURPOSE)
                if prose:
                    return prose
    for node in ast.walk(tree):
        if not _registers(node):
            continue
        name = ''
        description = ''
        for keyword in node.keywords:
            if keyword.arg == 'name' and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                name = keyword.value.value
            elif keyword.arg == 'description':
                description = _plain_text(keyword.value)
        if name == tool_name:
            prose = _safe_prose(description, MAX_PURPOSE)
            if prose:
                return prose
    docstring = ast.get_docstring(tree) or ''
    return _safe_prose(docstring.split('\n', 1)[0], MAX_PURPOSE)


def _action_packet(action: dict) -> dict:
    packet = {'name': action['name'], 'requires': list(action.get('requires') or [])}
    if action.get('note'):
        packet['note'] = action['note']
    return packet


def _each_skill(root: Path) -> list[tuple[str, Path]]:
    base = root / 'skills'
    if not base.is_dir():
        return []
    found = []
    try:
        children = [path for path in base.iterdir() if path.is_dir() and _keep_dir(path.name)]
    except OSError:
        return []
    for child in sorted(children, key=lambda path: path.name.lower()):
        try:
            skill_md = child / 'SKILL.md'
            if skill_md.is_file():
                found.append((child.name, skill_md))
            else:
                nested = [path for path in child.iterdir() if path.is_dir() and _keep_dir(path.name)]
                for folder in sorted(nested, key=lambda path: path.name.lower()):
                    nested_md = folder / 'SKILL.md'
                    if nested_md.is_file():
                        found.append((f'{child.name}/{folder.name}', nested_md))
                    if len(found) >= MAX_SKILLS:
                        return found
        except OSError:
            continue
        if len(found) >= MAX_SKILLS:
            break
    return found


def _skill_names(root: Path) -> list[str]:
    return [name for name, _path in _each_skill(root)]


def _frontmatter_description(path: Path) -> str:
    """The one-line description above the skill body. The body is not returned."""
    try:
        if not path.is_file() or path.stat().st_size > 200_000:
            return ''
        lines = []
        with path.open(encoding='utf-8', errors='replace') as handle:
            for index, line in enumerate(handle):
                if index >= 40:
                    break
                lines.append(line.rstrip('\n'))
                if index and line.strip() == '---':
                    break
    except OSError:
        return ''
    if lines and lines[0].strip() == '---':
        block = []
        for line in lines[1:]:
            if line.strip() == '---':
                break
            block.append(line)
    else:
        block = lines[:30]
    raw = ''
    chunks = []
    capture = False
    for line in block:
        if not capture:
            match = re.match(r'(?i)description:\s*(.*)$', line)
            if not match:
                continue
            rest = match.group(1).strip()
            if rest in {'>', '|', '>-', '|-', '>+', '|+'}:
                capture = True
                continue
            raw = rest
            break
        if line.startswith((' ', '\t')):
            chunks.append(line.strip())
            continue
        break
    if capture:
        raw = ' '.join(chunks)
    return _safe_prose(raw.strip().strip('"').strip("'"), 180)


def _skill_briefs(root: Path) -> list[dict]:
    briefs = []
    for name, path in _each_skill(root):
        summary = _frontmatter_description(path)
        if summary:
            briefs.append({'name': name, 'summary': summary})
    return briefs


def _skill_contracts(root: Path) -> list[dict]:
    """Compact call surface for each skill. Prose, secrets, and paths stay out."""
    contracts = []
    for name, path in _each_skill(root):
        front, body = _skill_text(path)
        summary = _frontmatter_description(path)
        related = _related_skills(front)
        actions = _command_actions(body) or _heading_actions(body)
        if name.startswith('custom/') or not summary and not related and not actions:
            continue
        contract = {'name': name, 'related': related, 'actions': actions}
        if summary:
            contract['summary'] = summary
        contracts.append(contract)
    return contracts


def _skill_text(path: Path) -> tuple[str, list[str]]:
    try:
        if not path.is_file() or path.stat().st_size > 200_000:
            return '', []
        raw = path.read_text(encoding='utf-8', errors='replace')[:100_000]
    except OSError:
        return '', []
    lines = raw.splitlines()
    if lines and lines[0].strip() == '---':
        for index in range(1, min(len(lines), 80)):
            if lines[index].strip() == '---':
                return '\n'.join(lines[1:index]), lines[index + 1:index + 701]
    return '', lines[:700]


def _related_skills(frontmatter: str) -> list[str]:
    found = []
    for chunk in re.findall(r'(?i)related_skills:\s*\[([^\]]*)\]', frontmatter):
        for part in chunk.split(','):
            name = part.strip().strip('"').strip("'")
            if re.fullmatch(r'[A-Za-z0-9_.:/-]{1,80}', name):
                found.append(name)
    rows = frontmatter.splitlines()
    for index, line in enumerate(rows):
        if not re.match(r'(?i)related_skills:\s*$', line.strip()):
            continue
        for nxt in rows[index + 1:index + 9]:
            item = re.match(r'\s*-\s*([A-Za-z0-9_.:/-]{1,80})\s*$', nxt)
            if not item:
                break
            found.append(item.group(1))
    unique = []
    for name in found:
        if name not in unique:
            unique.append(name)
    return unique[:8]


def _command_actions(lines: list[str]) -> list[dict]:
    grouped: dict[str, list[tuple[list[str], list[str]]]] = {}
    in_fence = False
    fence = ''
    for raw in lines:
        line = raw.strip()
        if line.startswith('```'):
            if not in_fence:
                in_fence = True
                fence = line[3:].strip().lower().split()[0] if line[3:].strip() else ''
            else:
                in_fence = False
                fence = ''
            continue
        if in_fence and fence not in SHELL_FENCES:
            continue
        if not in_fence and not line.startswith('$'):
            continue
        if line.startswith('#') or '|' in line or '<<' in line:
            continue
        cleaned = line[1:].strip() if line.startswith('$') else line
        if not cleaned or len(cleaned) > 240 or _ASSIGNMENT.match(cleaned):
            continue
        lowered = cleaned.lower()
        if any(mark in lowered for mark in SECRET_LINE):
            continue
        if any(re.search(pattern, cleaned) for pattern in SECRET_PATTERNS):
            continue
        try:
            tokens = shlex.split(cleaned, posix=True)
        except ValueError:
            continue
        parsed = _parse_command(tokens)
        if parsed is None:
            continue
        name, requires, optional = parsed
        grouped.setdefault(name, []).append((requires, optional))
        if len(grouped) >= MAX_SKILL_ACTIONS:
            break
    actions = []
    for name, samples in grouped.items():
        required = _shared(samples, 0)
        seen = set(required)
        optional = []
        for sample in samples:
            for item in sample[0] + sample[1]:
                if item not in seen:
                    seen.add(item)
                    optional.append(item)
        packet = {'name': name, 'requires': required[:8], 'kind': 'command'}
        note = _safe_prose('optional ' + ', '.join(optional[:6]), MAX_NOTE) if optional else ''
        if note:
            packet['note'] = note
        actions.append(packet)
    return actions


_ASSIGNMENT = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*\s*=')
_PLACEHOLDER = re.compile(r'^[A-Z][A-Z0-9_]{1,40}$')
_COMMAND_WORD = re.compile(r'^[a-z][a-z0-9_-]*$')
_POSITIONAL = {
    'search': 'query', 'find': 'query', 'get': 'id', 'read': 'id', 'reply': 'id',
    'list': 'query', 'send': 'message',
}


def _parse_command(tokens: list[str]) -> tuple[str, list[str], list[str]] | None:
    while tokens and not tokens[0].startswith('-'):
        token = tokens[0]
        if '=' in token or token.startswith('$') or token in SKIP_BINS or not _COMMAND_WORD.fullmatch(token):
            tokens = tokens[1:]
            continue
        break
    name_parts = []
    index = 0
    while index < len(tokens) and len(name_parts) < 3 and _COMMAND_WORD.fullmatch(tokens[index]):
        name_parts.append(tokens[index])
        index += 1
    if len(name_parts) < 2 or name_parts[0] in SKIP_BINS:
        return None
    requires = []
    optional = []
    positionals = 0
    while index < len(tokens):
        token = tokens[index]
        if token.startswith('-') and len(token) > 1:
            flag = token.split('=', 1)[0]
            if any(mark in flag.lower() for mark in ('secret', 'password', 'token', 'key')):
                return None
            inline = '=' in token
            takes_value = inline or (index + 1 < len(tokens) and not tokens[index + 1].startswith('-'))
            if takes_value:
                requires.append(flag)
                if not inline:
                    index += 1
            else:
                optional.append(flag)
            index += 1
            continue
        if _PLACEHOLDER.fullmatch(token):
            requires.append(token)
            index += 1
            continue
        if re.fullmatch(r'\d+', token):
            if 'id' not in requires:
                requires.append('id')
            index += 1
            continue
        positionals += 1
        index += 1
    if positionals:
        label = _POSITIONAL.get(name_parts[-1], 'value')
        if label not in requires:
            requires.insert(0, label)
    return ' '.join(name_parts), requires, optional


def _shared(samples: list[tuple[list[str], list[str]]], side: int) -> list[str]:
    if not samples:
        return []
    common = []
    for item in samples[0][side]:
        if item not in common and all(item in sample[side] for sample in samples):
            common.append(item)
    return common


_HEADING = re.compile(r'^#{2,4}\s+(?:\d+[.)]\s*)?(.+?)\s*$')
_HEADING_SKIP = {
    'references', 'scripts', 'when to use', 'pitfalls', 'troubleshooting', 'notes', 'rules',
    'verification', 'output format', 'output shape', 'first-time setup', 'usage', 'objective',
    'procedure', 'prerequisites', 'installation', 'configuration setup', 'debugging', 'tips',
    'supporting files', 'common operations',
}


def _heading_actions(lines: list[str]) -> list[dict]:
    actions = []
    for raw in lines:
        match = _HEADING.match(raw.strip())
        if not match:
            continue
        title = match.group(1).strip(' *_`')
        if title.lower() in _HEADING_SKIP or len(title) < 4 or len(title) > 80 or '/' in title:
            continue
        name = _safe_prose(title, 80)
        if not name:
            continue
        actions.append({'name': name, 'requires': [], 'kind': 'heading'})
        if len(actions) >= 8:
            break
    return actions


def _keep_dir(name: str) -> bool:
    lowered = name.lower()
    return name not in SKIP_DIRS and not name.startswith('.') and not lowered.endswith('-cache')


def _memory_names(root: Path) -> list[str]:
    base = root / 'memories'
    names = []
    for name in ('MEMORY.md', 'USER.md'):
        candidate = base / name
        if candidate.is_file():
            names.append(name)
    return names


def _memory_understanding(root: Path, names: list[str]) -> dict:
    roles = {
        'MEMORY.md': 'Durable facts the bot keeps across sessions. The memory tool reads and updates them.',
        'USER.md': 'The person profile. A skill may ask the memory tool to read it. The profile text is not copied into the skill.',
    }
    files = []
    for name in names:
        entry = {'name': name, 'role': roles.get(name, 'A memory file reached through the memory tool.')}
        files.append(entry)
    return {
        'files': files,
        'how': (
            'Memory survives across sessions. MEMORY.md holds durable facts. '
            'USER.md is the person profile and is not copied into a skill. '
            'The bot reaches both through the memory tool and the actions listed for that tool. '
            'A skill names that tool and the action. It does not invent a second memory store.'
        ),
    }


def _nexus_understanding(root: Path, skills: list[str], tools: list[str], memories: list[str]) -> dict:
    return {
        'hub': root.name,
        'counts': {'skills': len(skills), 'memories': len(memories), 'tools': len(tools)},
        'skill_groups': _nexus_labels(skills),
        'memories': memories,
        'how': (
            'The nexus is the map of this harness. The hub connects skill groups, memory files, and tools. '
            'A new skill is another skill node. It may call tools that are already on the map. '
            'It does not add a tool, start the harness, or replace an existing skill.'
        ),
    }


def _config_outline(path: Path) -> tuple[list[str], list[str]]:
    """Top-level section names and tool list items. Values are never kept."""
    if not path.is_file():
        return [], []
    try:
        if path.stat().st_size > 262144:
            return [], []
        lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError:
        return [], []
    sections: list[str] = []
    tools: list[str] = []
    current = ''
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        if SECRET_NAME.search(stripped.split(':', 1)[0]):
            current = ''
            continue
        indented = line[:1] in ' \t'
        if not indented:
            key = stripped.split(':', 1)[0].strip().strip('"').strip("'")
            current = key if IDENT.fullmatch(key) and not SECRET_NAME.search(key) else ''
            if current and current not in sections:
                sections.append(current)
            continue
        if current in {'toolsets', 'tools', 'enabled_toolsets'} and stripped.startswith('- '):
            name = stripped[2:].split('#', 1)[0].strip().strip('"').strip("'")
            name = name.split(':', 1)[0].strip()
            if IDENT.fullmatch(name) and not SECRET_NAME.search(name) and name not in tools:
                tools.append(name)
            if len(tools) >= MAX_TOOLS:
                break
    return tools, sections[:40]
