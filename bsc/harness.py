"""Read-only map of one Hermes home. Nothing here starts Hermes or reads secrets."""
from __future__ import annotations
from datetime import datetime, timezone
from hashlib import sha256
import os
from pathlib import Path
import re

from .security import InputError, no_secrets

MARKERS = ('config.yaml', '.env', 'state.db')
SKIP_DIRS = {
    '.git', '.hg', '.svn', '__pycache__', 'node_modules', 'models', 'runtimes',
    'node', '.venv', 'venv', 'dist', '.deleted', '.cache',
}
SECRET_NAME = re.compile(r'(?i)(api[_-]?key|secret|password|token|credential|authorization|\.env$)')
IDENT = re.compile(r'^[A-Za-z0-9_.:/-]{1,80}$')
MAX_SKILLS = 80
MAX_TOOLS = 40


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
    """Names the accepted folder already exposes. File contents stay unread."""
    try:
        root = _verified_root(path)
    except InputError:
        return None
    tools, _sections = _tool_names(root)
    catalog = {
        'name': root.name,
        'skills': _skill_names(root),
        'tools': tools,
        'memory_files': _memory_names(root),
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


def _skill_names(root: Path) -> list[str]:
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
            if (child / 'SKILL.md').is_file():
                found.append(child.name)
            else:
                nested = [path for path in child.iterdir() if path.is_dir() and _keep_dir(path.name)]
                for folder in sorted(nested, key=lambda path: path.name.lower()):
                    if (folder / 'SKILL.md').is_file():
                        found.append(f'{child.name}/{folder.name}')
                    if len(found) >= MAX_SKILLS:
                        return found
        except OSError:
            continue
        if len(found) >= MAX_SKILLS:
            break
    return found


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
