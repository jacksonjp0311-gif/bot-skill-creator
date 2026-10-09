"""Static checks for declared harness calls. Never executes a harness operation."""
import re
from .security import InputError, text


def _optional_inputs(action: dict) -> set[str]:
    note = action.get('note')
    if not isinstance(note, str):
        return set()
    match = re.match(r'(?i)^optional\s+(.+)$', note.strip())
    if not match:
        return set()
    return {part.strip() for part in match.group(1).split(',') if part.strip()}


def declarations(value):
    if not isinstance(value, list) or len(value) > 32:
        raise InputError('Capability calls must be a list with at most 32 entries.')
    result = []
    for call in value:
        if not isinstance(call, dict) or call.get('kind') not in {'tool', 'skill'}:
            raise InputError('Each capability call needs kind tool or skill.')
        inputs = call.get('inputs', {})
        if not isinstance(inputs, dict) or len(inputs) > 24:
            raise InputError('Call inputs must map parameter names to their sources.')
        result.append({'kind': call['kind'], 'name': text(call.get('name'), 'Capability', 180),
                       'action': text(call.get('action'), 'Action', 180),
                       'inputs': {text(k, 'Parameter', 100): text(v, 'Input source', 500)
                                  for k, v in inputs.items()}})
    return result


def surface(catalog):
    result = {}
    for kind, entries in [('tool', catalog.get('tools', [])), ('skill', catalog.get('skill_contracts', []))]:
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            for action in entry.get('actions', []):
                if isinstance(action, str):
                    action = {'name': action}
                if kind == 'skill' and action.get('kind') not in {'command', 'heading', None}:
                    continue
                required = set(action.get('requires', []))
                required.update(x['name'] for x in entry.get('inputs', [])
                                if isinstance(x, dict) and x.get('required'))
                result[(kind, entry['name'], action['name'])] = required
    return result


def infer_calls(plan, catalog):
    """Compatibility for old drafts: only explicit, catalog-named calls are inferred."""
    steps = '\n'.join(plan.get('steps', []))
    calls = []
    for (kind, name, action), required in surface(catalog).items():
        patterns = [r'\b(?:call|invoke|run)\s+`?' + re.escape(action) + r'(?=\b|`)',
                    r'\b(?:call|invoke|run)\s+`?' + re.escape(name) + r'[.\s]+' + re.escape(action) + r'(?=\b|`)']
        if any(re.search(p, steps, re.I) for p in patterns) and (kind == 'tool' or name in steps):
            inputs = {key: 'Resolve ' + key + ' from the user or an earlier verified result.'
                      for key in required if re.search(r'(?<!\w)' + re.escape(key) + r'(?!\w)', steps)}
            calls.append({'kind': kind, 'name': name, 'action': action, 'inputs': inputs})
    return calls


def _call_names(known):
    """Catalog names that make the word after call/invoke/execute a real invocation."""
    exact, actions = set(), set()
    for _kind, name, action in known:
        exact.update({name.lower(), action.lower(), f'{name}.{action}'.lower()})
        actions.add(action.lower())
    return exact, actions


def _names_a_capability(first, second, exact, actions):
    """Ordinary English is not a call. A path, catalog name, or full action is."""
    if '/' in first or '.' in first:
        return True
    low = first.lower()
    if low in exact:
        return True
    return bool(second) and f'{low} {second.lower()}' in actions


def errors(plan, catalog):
    known = surface(catalog)
    exact, action_names = _call_names(known)
    calls = plan.get('capability_calls', infer_calls(plan, catalog))
    problems = []
    declared = set()
    for call in calls:
        key = (call['kind'], call['name'], call['action'])
        declared.add(key)
        if key not in known:
            problems.append('Unsupported harness call: ' + call['name'] + '.' + call['action'])
        else:
            missing = known[key] - set(call['inputs'])
            if missing:
                problems.append('Missing inputs for ' + call['name'] + '.' + call['action'] + ': ' + ', '.join(sorted(missing)))
            entries = catalog.get('tools' if key[0] == 'tool' else 'skill_contracts', [])
            entry = next((e for e in entries if isinstance(e, dict) and e['name'] == key[1]), {})
            allowed = set(known[key])
            allowed.update(x['name'] if isinstance(x, dict) else x for x in entry.get('inputs', []))
            for action in entry.get('actions') or []:
                if isinstance(action, dict) and action.get('name') == key[2]:
                    allowed.update(_optional_inputs(action))
            if allowed:
                unknown = set(call['inputs']) - allowed
                if unknown:
                    problems.append('Undocumented inputs for ' + call['name'] + '.' + call['action'] + ': ' + ', '.join(sorted(unknown)))
    blob = '\n'.join(plan.get('steps', []))
    for tool in catalog.get('tools', []):
        if isinstance(tool, dict) and re.search(r'\b' + re.escape(tool['name']) + r'\b', blob):
            if not any(key[0] == 'tool' and key[1] == tool['name'] for key in declared):
                problems.append('No declared, inspectable action for tool: ' + tool['name'])
    # Catch explicit calls in prose, including invented actions on a real tool.
    # "Do not call a separate related skill" is English. "Call memory teleport_money" is not.
    for step in plan.get('steps', []):
        for match in re.finditer(r'\b(?:call|invoke|execute)\s+`?([a-zA-Z_][\w./-]*)(?:\s+([a-zA-Z_][\w-]*))?', step, re.I):
            first, second = match.groups()
            first = first.rstrip('.')
            if re.search(r'\bnot\s+$', step[max(0, match.start() - 12):match.start()].lower()):
                continue
            if not _names_a_capability(first, second, exact, action_names):
                continue
            first_l = first.lower()
            second_l = second.lower() if second else ''
            candidates = {key for key in known
                          if first_l in {key[1].lower(), key[2].lower(), (key[1] + '.' + key[2]).lower()}
                          or (second and key[2].lower() == first_l + ' ' + second_l)}
            if second and second_l not in {'with', 'using', 'only', 'from', 'to', 'and', 'after', 'before', 'for', 'if', 'when', 'then', 'action'}:
                narrowed = {key for key in candidates if key[2].lower() in {second_l, first_l + ' ' + second_l}}
                if narrowed or any(key[1].lower() == first_l for key in candidates):
                    candidates = narrowed
            if not candidates:
                problems.append('Unrecognized explicit call: ' + first + (' ' + second if second else ''))
            elif not (candidates & declared):
                problems.append('Declare the exact capability call and its input sources: ' + first)
    return list(dict.fromkeys(problems))
