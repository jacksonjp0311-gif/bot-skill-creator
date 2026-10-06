"""Find the Ollama server already running on this machine.

The default scan reads Ollama at 127.0.0.1:11434 and does not probe other
local programs. An explicit candidate list can still read one loopback
OpenAI-compatible URL. Nothing is sent off the computer, and a server that
does not answer is skipped.
"""
from __future__ import annotations
import json
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener
from .providers import NoRedirect
from .security import InputError, endpoint

# Well-known local servers. The port decides the guess; the response can correct it.
_CANDIDATES = (
    (11434, 'Ollama'),
    (1234, 'LM Studio'),
    (8080, 'llama.cpp'),
    (8081, 'llama.cpp'),
    (8000, 'vLLM'),
    (8001, 'vLLM'),
    (1337, 'Jan'),
    (5000, 'text-generation-webui'),
    (5001, 'KoboldCPP'),
    (4891, 'GPT4All'),
)
_OPENER = build_opener(ProxyHandler({}), NoRedirect())


def discover_local_models(candidates=None, timeout=0.6, ollama_origin=None):
    """Return Ollama models, unless a test passes an explicit loopback list."""
    if candidates is None:
        origin = (ollama_origin or 'http://127.0.0.1:11434').rstrip('/')
        return {'models': _dedupe(_discover_ollama(origin, timeout))}
    found = []
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(candidates)))) as pool:
        for models in pool.map(lambda base: _probe(base, timeout), candidates):
            found.extend(models)
    return {'models': _dedupe(found)}


def _discover_ollama(origin, timeout):
    try:
        origin = endpoint(origin, local=True)
    except InputError:
        return []
    chat = origin + '/v1'
    try:
        _header, payload = _get(origin + '/api/tags', timeout)
    except (OSError, ValueError, TimeoutError, json.JSONDecodeError):
        return [model for model in _probe(chat, timeout) if not _skip_harness(model['id'])]
    models = []
    for item in _entries(payload, 'models'):
        model_id = _model_id(item)
        if not model_id or _skip_harness(model_id):
            continue
        models.append({
            'id': model_id,
            'label': _label(model_id),
            'detail': _detail('Ollama', _item_meta(item)),
            'server': 'Ollama',
            'base_url': chat,
            'token_field': 'max_tokens',
            'json_mode': False,
            'local': True,
        })
    return models


def _dedupe(found):
    unique = []
    seen = set()
    for model in found:
        key = (model['base_url'], model['id'])
        if key in seen:
            continue
        seen.add(key)
        unique.append(model)
    unique.sort(key=lambda item: (item['server'].lower(), item['label'].lower()))
    return unique


def _skip_harness(model_id):
    """Ignore this workstation's harness and raw model-file paths."""
    if 'pegasus' in model_id.lower():
        return True
    return bool(re.match(r'^[a-z]:[\\/]', model_id, flags=re.IGNORECASE))


def _probe(base, timeout):
    try:
        base = endpoint(base, local=True)
    except InputError:
        return []
    try:
        header, payload = _get(base + '/models', timeout)
    except (OSError, ValueError, TimeoutError, json.JSONDecodeError):
        return []
    server = _server_name(base, header, payload)
    # llama.cpp lists the same model twice: a thin `models` entry and a `data`
    # entry that carries context size and quantization. Keep the richer fields.
    details = {}
    for item in _entries(payload, 'data') + _entries(payload, 'models'):
        model_id = _model_id(item)
        if not model_id:
            continue
        incoming = _item_meta(item)
        current = details.get(model_id)
        if current is None:
            details[model_id] = incoming
            continue
        for key, value in incoming.items():
            if _filled(value) and not _filled(current.get(key)):
                current[key] = value
    models = []
    for model_id, meta in details.items():
        models.append({
            'id': model_id,
            'label': _label(model_id),
            'detail': _detail(server, meta),
            'server': server,
            'base_url': base,
            'token_field': 'max_tokens',
            'json_mode': False,
            'local': True,
        })
    return models


def _get(url, timeout):
    request = Request(url, headers={'Accept': 'application/json'})
    with _OPENER.open(request, timeout=timeout) as response:
        raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError('too large')
        return response.headers.get('Server', ''), json.loads(raw.decode('utf-8'))


def _entries(payload, key):
    value = payload.get(key) if isinstance(payload, dict) else None
    return [item for item in value if isinstance(item, (dict, str))] if isinstance(value, list) else []


def _filled(value):
    if isinstance(value, str):
        return bool(value.strip())
    return value is not None and value is not False


def _item_meta(item):
    if not isinstance(item, dict):
        return {}
    meta = item.get('meta') if isinstance(item.get('meta'), dict) else {}
    extra = item.get('details') if isinstance(item.get('details'), dict) else {}
    merged = {**extra, **meta}
    quant = extra.get('quantization_level') or meta.get('quantization_level') or meta.get('ftype')
    size = extra.get('parameter_size') or meta.get('parameter_size')
    if _filled(quant):
        merged['quantization_level'] = quant
    if _filled(size):
        merged['parameter_size'] = size
    return merged


def _model_id(item):
    if isinstance(item, str):
        return item.strip()
    for key in ('id', 'name', 'model'):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ''


def _server_name(base, header, payload):
    evidence = ' '.join([header or '', json.dumps(payload)[:500]]).lower()
    if 'llama.cpp' in evidence or 'llamacpp' in evidence:
        return 'llama.cpp'
    if 'ollama' in evidence:
        return 'Ollama'
    if 'lm studio' in evidence or 'lmstudio' in evidence:
        return 'LM Studio'
    if 'vllm' in evidence:
        return 'vLLM'
    port = urlsplit(base).port
    for candidate_port, name in _CANDIDATES:
        if candidate_port == port:
            return name
    return 'Local server'


def _label(model_id):
    leaf = model_id.replace('\\', '/').rsplit('/', 1)[-1]
    leaf = re.sub(r'\.(?:gguf|bin|safetensors)$', '', leaf, flags=re.IGNORECASE)
    leaf = re.sub(r':latest$', '', leaf, flags=re.IGNORECASE)
    leaf = re.sub(r'[-_.](?:q\d.*|fp16|bf16|f16|f32)$', '', leaf, flags=re.IGNORECASE)
    return leaf or model_id


def _parameter_size(meta):
    size = meta.get('parameter_size')
    if isinstance(size, str) and size.strip():
        return size.strip()
    count = size if isinstance(size, (int, float)) else meta.get('n_params')
    if isinstance(count, (int, float)) and count >= 1_000_000_000:
        return f'{count / 1_000_000_000:.1f}B'
    return ''


def _detail(server, meta):
    parts = [server]
    quant = meta.get('quantization_level') or meta.get('ftype')
    if isinstance(quant, str) and quant.strip():
        parts.append(quant.strip())
    size = _parameter_size(meta)
    if size:
        parts.append(size)
    context = meta.get('n_ctx')
    if isinstance(context, int) and context > 0:
        parts.append(f'{context // 1024}K context' if context >= 1024 else f'{context} context')
    return ' · '.join(parts)
