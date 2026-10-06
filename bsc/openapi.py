"""Read-only OpenAPI 3.0/3.1 JSON capability importer. No HTTP, no code execution."""
from __future__ import annotations
from hashlib import sha256
import json
import re
from .security import InputError, endpoint, no_secrets, slug, text

METHODS = {'get', 'head', 'post', 'put', 'patch', 'delete', 'options'}
SCHEMA_KEYS = {'type', 'format', 'description', 'enum', 'items', 'properties', 'required',
               'additionalProperties', 'nullable', 'minimum', 'maximum', 'minLength',
               'maxLength', 'oneOf', 'anyOf', 'allOf', 'pattern', 'title'}


def ref(node, doc, seen=()):
    if not isinstance(node, dict) or '$ref' not in node:
        return node
    pointer = node['$ref']
    if not isinstance(pointer, str) or not pointer.startswith('#/'):
        raise InputError('External $ref is unsupported. Bundle the OpenAPI JSON locally first.')
    if pointer in seen or len(seen) > 20:
        raise InputError('Cyclic or excessively nested OpenAPI reference.')
    result = doc
    try:
        for key in pointer[2:].split('/'):
            result = result[key.replace('~1', '/').replace('~0', '~')]
    except (KeyError, TypeError) as exc:
        raise InputError('Unresolved OpenAPI reference.') from exc
    return ref(result, doc, (*seen, pointer))


def schema(node, doc, depth=0):
    if depth > 12:
        raise InputError('Schema nesting is too deep for this importer.')
    node = ref(node, doc)
    if isinstance(node, bool):
        return node
    if not isinstance(node, dict):
        raise InputError('Schema must be an object.')
    out = {}
    for key, value in node.items():
        if key not in SCHEMA_KEYS:
            continue  # Examples/defaults/extensions may carry private data; never export them.
        if key == 'properties':
            if not isinstance(value, dict):
                raise InputError('Schema properties must be an object.')
            out[key] = {str(k): schema(v, doc, depth + 1) for k, v in value.items()}
        elif key in {'items', 'additionalProperties'} and isinstance(value, (dict, bool)):
            out[key] = schema(value, doc, depth + 1)
        elif key in {'oneOf', 'anyOf', 'allOf'}:
            if not isinstance(value, list):
                raise InputError('Schema alternatives must be an array.')
            out[key] = [schema(v, doc, depth + 1) for v in value]
        else:
            out[key] = value
    return out


def import_document(raw: str) -> dict:
    raw = text(raw, 'OpenAPI JSON', 1000000)
    try:
        doc = json.loads(raw)
    except (ValueError, RecursionError) as exc:
        raise InputError('Import a bundled OpenAPI 3.0 or 3.1 JSON document. YAML is not supported in v0.1.') from exc
    if not isinstance(doc, dict) or not str(doc.get('openapi', '')).startswith(('3.0.', '3.1.')):
        raise InputError('Expected OpenAPI 3.0.x or 3.1.x JSON.')
    paths = doc.get('paths', {})
    if not isinstance(paths, dict):
        raise InputError('OpenAPI paths must be an object.')
    servers = doc.get('servers') or []
    if not isinstance(servers, list):
        raise InputError('OpenAPI servers must be an array.')
    base_url = ''
    if servers:
        base_url = endpoint(servers[0].get('url', ''))
    operations, ids, warnings = [], set(), []
    for path, raw_path in paths.items():
        if not isinstance(path, str) or not path.startswith('/') or '..' in path:
            raise InputError('Invalid OpenAPI path.')
        item = ref(raw_path, doc)
        if not isinstance(item, dict):
            raise InputError('Path item must be an object.')
        for method, raw_op in item.items():
            if method not in METHODS:
                continue
            op = ref(raw_op, doc)
            if not isinstance(op, dict):
                raise InputError('Operation must be an object.')
            if 'servers' in item or 'servers' in op:
                raise InputError('Per-operation servers are unsupported; split into single-server documents.')
            op_id = op.get('operationId') or slug(f'{method}-{path}')
            if not isinstance(op_id, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', op_id) or op_id in ids:
                raise InputError('Operation IDs must be unique simple identifiers.')
            ids.add(op_id)
            params = {}
            combined = item.get('parameters', []) + op.get('parameters', [])
            for raw_param in combined:
                param = ref(raw_param, doc)
                where = param.get('in')
                if where not in {'path', 'query', 'header', 'cookie'}:
                    raise InputError('Invalid parameter location.')
                name = text(param.get('name'), 'Parameter name', 150)
                params[(where, name)] = {'name': name, 'in': where,
                    'required': bool(param.get('required')) or where == 'path',
                    'schema': schema(param.get('schema', {}), doc)}
            body = None
            if 'requestBody' in op:
                request = ref(op['requestBody'], doc)
                content = request.get('content', {})
                if 'application/json' in content:
                    body = {'required': bool(request.get('required')),
                            'schema': schema(content['application/json'].get('schema', {}), doc)}
                else:
                    warnings.append(f'{op_id}: non-JSON request body requires a custom host adapter.')
            security = op.get('security', doc.get('security', []))
            responses = op.get('responses', {})
            operation = {'id': op_id, 'method': method.upper(), 'path': path,
                'summary': text(op.get('summary') or op_id, 'Operation summary', 500),
                'parameters': list(params.values()), 'request_body': body,
                'response_codes': list(responses)[:30],
                'security': security,
                'requires_host_approval': True,
                'effect': 'read_candidate' if method in {'get', 'head', 'options'} else 'write_candidate'}
            operations.append(operation)
            if len(operations) > 150:
                raise InputError('Import at most 150 operations per document; reduce the spec first.')
    if not operations:
        raise InputError('No supported operations were found.')
    schemes = {}
    for key, raw_scheme in doc.get('components', {}).get('securitySchemes', {}).items():
        val = ref(raw_scheme, doc)
        schemes[key] = {k: val[k] for k in ('type', 'scheme', 'in', 'name', 'bearerFormat') if k in val}
        schemes[key]['credential_env'] = re.sub(r'[^A-Z0-9_]', '_', str(key).upper()) + '_TOKEN'
        if val.get('type') not in {'http', 'apiKey'}:
            warnings.append(f'{key}: authentication requires a host-managed OAuth/OpenID adapter.')
    result = {'name': text(doc.get('info', {}).get('title') or 'Imported API', 'API title', 150),
              'base_url': base_url, 'openapi_version': doc['openapi'],
              'source_sha256': sha256(raw.encode()).hexdigest(), 'operations': operations,
              'security_schemes': schemes, 'warnings': warnings,
              'status': 'contract_only_not_connected'}
    no_secrets(result)
    if not base_url:
        result['warnings'].append('No root server URL; provide the endpoint in your host adapter.')
    return result
