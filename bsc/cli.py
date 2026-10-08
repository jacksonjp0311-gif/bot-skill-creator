"""CLI and newline-delimited JSON bridge for agent harnesses."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
from . import __version__, core, openapi, providers
from .security import InputError


def make_plan(brief, api, selected, name=None, model=False):
    ops = [x for x in (api or {}).get('operations', []) if x['id'] in selected]
    if model:
        cfg = {'base_url': os.environ.get('BSC_MODEL_BASE_URL'), 'model': os.environ.get('BSC_MODEL'),
               'local': os.environ.get('BSC_MODEL_LOCAL') == '1',
               'json_mode': os.environ.get('BSC_MODEL_JSON', '1') == '1',
               'token_field': os.environ.get('BSC_MODEL_TOKEN_FIELD', 'max_completion_tokens')}
        plan = core.validate_plan(providers.draft(cfg, messages=[{'role': 'user', 'content': brief}],
                                                current_plan=None, selected_operations=ops))
    else:
        plan = core.offline_plan(brief, ops)
    if name:
        plan['name'] = name
    return core.validate_plan(plan)


def dispatch(request):
    """JSON bridge is authoring-only; it never executes business API operations.

    Caller owns subprocess filesystem permissions. This is NDJSON, not MCP.
    Commands validate and preview are read-only; create writes only on explicit action.
    """
    action = request.get('action')
    if action == 'workspace':
        from .workspace import Workspace
        ws = Workspace(Path(request['workspace']))
        operation = request.get('operation')
        if operation == 'harnesses':
            return ws.harness_list()
        if operation == 'connect':
            return ws.accept_harness(request.get('path'), request.get('agreed'))
        if operation == 'switch':
            return ws.switch_harness(request.get('harness_id'))
        if operation == 'context':
            return ws.set_harness_context(request.get('harness_id'), request.get('context'))
        if operation == 'projects':
            return ws.list()
        if operation == 'create':
            return ws.create(request['harness_id']) if 'harness_id' in request else ws.create()
        if operation == 'chat':
            return ws.chat(request.get('id'), request.get('message'))
        if operation == 'validate':
            return ws.validate(request.get('id'))
        if operation == 'install':
            return ws.install(request.get('id'), request.get('fingerprint'), request.get('approved'))
        raise InputError('Unknown workspace operation.')
    if action == 'score':
        return core.score(**request.get('counts', {}))
    if action == 'import':
        return openapi.import_document(request['document'])
    if action in {'preview', 'create'}:
        api = openapi.import_document(request['openapi']) if request.get('openapi') else None
        selected = request.get('operations', [])
        plan = core.validate_plan(request['plan']) if request.get('plan') else make_plan(request['brief'], api, selected, request.get('name'))
        files = core.compile_package(plan, api, selected)
        if action == 'preview':
            return {'plan': plan, 'files': {k: v.decode() for k, v in files.items()}, 'validation': core.validate_files(files)}
        target = core.write_package(Path(request['output']), plan, api, selected)
        return {'path': str(target), 'name': plan['name'], 'validation': core.validate_files(files)}
    if action == 'validate':
        return core.validate_files(core.read_package(Path(request['path'])))
    raise InputError('Unknown bridge action. Use preview, create, validate, import, or score.')


def parser():
    p = argparse.ArgumentParser(prog='bsc', description='Bot Skill Creator — describe it, inspect it, export it.')
    p.add_argument('--version', action='version', version=__version__)
    s = p.add_subparsers(dest='command', required=True)
    web = s.add_parser('serve', help='Launch the private browser studio')
    web.add_argument('--port', type=int, default=8717)
    web.add_argument('--workspace', type=Path, default=Path.home() / '.bot-skill-creator')
    web.add_argument('--open', action='store_true', help='Accepted for older commands. The studio opens with the page unless --stay is set.')
    web.add_argument('--no-browser', action='store_true', help='Follow the page without asking Python to open it. The launcher opens the browser.')
    web.add_argument('--stay', action='store_true', help='Leave the server running until Ctrl+C and do not open a browser.')
    for command in ('create', 'preview'):
        x = s.add_parser(command, help='Compile a reviewed JSON plan or a deterministic brief template')
        x.add_argument('--brief')
        x.add_argument('--brief-file', type=Path)
        x.add_argument('--plan', type=Path)
        x.add_argument('--name')
        x.add_argument('--openapi', type=Path)
        x.add_argument('--operations', default='', help='Comma-separated operation IDs; default selects none')
        x.add_argument('--out', type=Path, default=Path('exports'))
        x.add_argument('--model', action='store_true', help='Explicitly send the brief to the configured model API')
    v = s.add_parser('validate', help='Check package structure and all declared checksums')
    v.add_argument('path', type=Path)
    z = s.add_parser('zip', help='Export an existing validated skill folder')
    z.add_argument('path', type=Path)
    z.add_argument('--out', type=Path, required=True)
    i = s.add_parser('import-api', help='Inspect a local OpenAPI JSON document without network access')
    i.add_argument('path', type=Path)
    i = s.add_parser('install', help='Copy one exported skill into a chosen harness directory; never overwrite')
    i.add_argument('path', type=Path)
    i.add_argument('--target', type=Path, required=True)
    r = s.add_parser('score', help='Inspect the declared-prior routing estimate')
    for arg in ('success', 'failure', 'unknown'):
        r.add_argument('--' + arg, type=int, default=0)
    r.add_argument('--cost', type=float, default=.2)
    r.add_argument('--weight', type=float, default=.15)
    s.add_parser('bridge', help='Read one JSON request per stdin line; emit one JSON response per line')
    w = s.add_parser('workspace', help='Use the same persistent harness workflow as the studio')
    w.add_argument('--request-file', type=Path, required=True, help='JSON request with workspace and operation fields')
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == 'serve':
            from .server import serve
            # Every normal launch follows the studio page. --stay is the console exception.
            follow_page = not args.stay
            serve(args.workspace, args.port, open_browser=follow_page and not args.no_browser,
                  until_close=follow_page, quiet=follow_page)
            return 0
        if args.command == 'bridge':
            for line in sys.stdin:
                try:
                    if len(line) > 1200000:
                        raise InputError('Bridge request too large.')
                    req = json.loads(line)
                    if not isinstance(req, dict):
                        raise InputError('Request must be an object.')
                    result = {'ok': True, 'result': dispatch(req)}
                except Exception as exc:
                    result = {'ok': False, 'error': str(exc) if isinstance(exc, InputError) else 'Invalid bridge request or local operation failed.'}
                print(json.dumps(result, ensure_ascii=False), flush=True)
            return 0
        if args.command == 'workspace':
            request = json.loads(args.request_file.read_text(encoding='utf-8'))
            result = dispatch({**request, 'action': 'workspace'})
        elif args.command in {'create', 'preview'}:
            api = openapi.import_document(args.openapi.read_text(encoding='utf-8')) if args.openapi else None
            selected = [x.strip() for x in args.operations.split(',') if x.strip()]
            if args.plan:
                plan = core.validate_plan(json.loads(args.plan.read_text(encoding='utf-8')))
            else:
                brief = args.brief_file.read_text(encoding='utf-8') if args.brief_file else args.brief
                if not brief:
                    raise InputError('Provide --brief, --brief-file, or --plan.')
                plan = make_plan(brief, api, selected, args.name, args.model)
            files = core.compile_package(plan, api, selected)
            result = {'name': plan['name'], 'plan': plan, 'validation': core.validate_files(files)}
            if args.command == 'create':
                result['path'] = str(core.write_package(args.out, plan, api, selected))
            if args.command == 'preview':
                result['files'] = {k: v.decode() for k, v in files.items()}
        elif args.command == 'validate':
            result = core.validate_files(core.read_package(args.path))
        elif args.command == 'zip':
            files = core.read_package(args.path)
            meta = json.loads(files['skill.json'])
            if args.out.exists():
                raise InputError('Output exists; choose a new filename.')
            raw = core.zip_bytes(meta['name'], files)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_bytes(raw)
            result = {'path': str(args.out.resolve()), 'bytes': len(raw)}
        elif args.command == 'import-api':
            result = openapi.import_document(args.path.read_text(encoding='utf-8'))
        elif args.command == 'install':
            files = core.read_package(args.path)
            result = core.validate_files(files)
            if not result['ok']:
                raise InputError('Package validation failed: ' + '; '.join(result['errors']))
            name = json.loads(files['skill.json'])['name']
            target = args.target.resolve() / name
            if target.exists():
                raise InputError('The destination skill exists. It was not overwritten.')
            args.target.mkdir(parents=True, exist_ok=True)
            shutil.copytree(args.path, target)
            result['path'] = str(target)
        elif args.command == 'score':
            result = core.score(args.success, args.failure, args.unknown, args.cost, args.weight)
        print(core.pretty(result), end='')
        return 1 if result.get('ok') is False else 0
    except (InputError, OSError, ValueError, KeyError) as exc:
        print(core.pretty({'ok': False, 'error': str(exc) if isinstance(exc, InputError) else 'Invalid file, configuration, or unavailable local path.'}), end='', file=sys.stderr)
        return 1
