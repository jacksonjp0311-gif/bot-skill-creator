"""Single-user loopback web app. Deliberately refuses public bind addresses."""
from __future__ import annotations
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
from urllib.parse import urlsplit, parse_qs
import webbrowser
from . import __version__, core
from .security import InputError
from .discover import discover_local_models
from .workspace import Workspace

WEB = Path(__file__).parent / 'web'
ASSETS = {'/': ('index.html', 'text/html; charset=utf-8'),
          '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
          '/theme.js': ('theme.js', 'text/javascript; charset=utf-8'),
          '/style.css': ('style.css', 'text/css; charset=utf-8'),
          '/favicon.svg': ('favicon.svg', 'image/svg+xml')}

class AppServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, addr, workspace):
        if addr[0] != '127.0.0.1':
            raise ValueError('Only 127.0.0.1 is supported. Use a private local session, not a public deployment.')
        self.workspace = workspace
        self.token = secrets.token_urlsafe(32)
        super().__init__(addr, Handler)
        self.origin = f'http://127.0.0.1:{self.server_address[1]}'

class Handler(BaseHTTPRequestHandler):
    server_version = 'BotSkillCreator'
    sys_version = ''

    def log_message(self, format, *args):
        return  # Do not log chat content, tokens, query strings, or provider errors.

    def setup(self):
        super().setup()
        self.connection.settimeout(60)

    def send(self, status, body, content_type='application/json; charset=utf-8', filename=None):
        if isinstance(body, (dict, list)):
            body = core.pretty(body).encode()
        if isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.send_header('X-Frame-Options', 'DENY')
        if filename:
            self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)

    def boundary(self, *, write=False):
        expected_host = self.server.origin.split('://', 1)[1]
        if self.headers.get('Host') != expected_host:
            raise InputError('Unrecognized Host. Open the printed 127.0.0.1 URL.')
        origin = self.headers.get('Origin')
        if origin and origin != self.server.origin:
            raise InputError('Cross-origin requests are not allowed.')
        if self.headers.get('Sec-Fetch-Site') in {'cross-site', 'same-site'}:
            raise InputError('Cross-site requests are not allowed.')
        if write and not secrets.compare_digest(self.headers.get('X-BSC-Token', ''), self.server.token):
            raise InputError('Missing local session token. Refresh the application.')

    def do_GET(self):
        try:
            self.boundary()
            parsed = urlsplit(self.path)
            path = parsed.path
            if path in ASSETS:
                name, mime = ASSETS[path]
                self.send(200, (WEB / name).read_bytes(), mime)
            elif path == '/api/bootstrap':
                self.send(200, {'version': __version__, 'token': self.server.token,
                    'projects': self.server.workspace.list(), 'provider': self.server.workspace.provider_info(),
                    **self.server.workspace.secret_status()})
            elif path == '/api/local-models':
                self.boundary(write=True)
                self.send(200, discover_local_models())
            elif path == '/api/project':
                # Private content requires the session token even on GET.
                self.boundary(write=True)
                project_id = parse_qs(parsed.query).get('id', [''])[0]
                self.send(200, self.server.workspace.view(self.server.workspace.get(project_id)))
            elif path == '/api/example':
                self.send(200, json.loads((core.ROOT / 'examples' / 'warehouse.openapi.json').read_text()))
            elif path == '/api/math':
                self.send(200, {'markdown': (core.ROOT / 'docs' / 'MATH.md').read_text(encoding='utf-8')})
            else:
                self.send(404, {'error': 'Not found.'})
        except InputError as exc:
            self.send(403, {'error': str(exc)})
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception:
            self.send(500, {'error': 'Local operation failed. No provider credentials are included in this error.'})

    def do_POST(self):
        try:
            self.boundary(write=True)
            if self.headers.get('Transfer-Encoding'):
                raise InputError('Chunked requests are not supported.')
            if self.headers.get_content_type() != 'application/json':
                raise InputError('Use application/json.')
            try:
                length = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                raise InputError('Invalid request length.')
            if not 0 < length <= 1200000:
                raise InputError('Request exceeds the size limit.')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise InputError('JSON request must be an object.')
            ws = self.server.workspace
            path = urlsplit(self.path).path
            if path == '/api/projects':
                result = ws.create()
            elif path == '/api/projects/delete':
                result = ws.delete(data.get('id'))
            elif path == '/api/chat':
                result = ws.chat(data.get('id'), data.get('message'), data.get('tool_generation') if isinstance(data.get('tool_generation'), bool) else None)
            elif path == '/api/tool-generation':
                result = ws.set_tool_generation(data.get('id'), data.get('enabled'))
            elif path == '/api/import':
                result = ws.import_api(data.get('id'), data.get('document'))
            elif path == '/api/select':
                result = ws.select(data.get('id'), data.get('selected_ids'))
            elif path == '/api/plan':
                result = ws.edit_plan(data.get('id'), data.get('plan'))
            elif path == '/api/provider':
                result = ws.configure_provider(data)
            elif path == '/api/provider/key':
                result = ws.save_provider_key(data.get('provider'), data.get('api_key', ''))
            elif path == '/api/provider/disconnect':
                ws.provider = None
                result = ws.provider_info()
            elif path == '/api/export':
                name, raw = ws.export(data.get('id'), data.get('fingerprint'))
                self.send(200, raw, 'application/zip', name)
                return
            elif path == '/api/score':
                result = core.score(**{k: data[k] for k in ('success', 'failure', 'unknown', 'cost', 'weight') if k in data})
            else:
                self.send(404, {'error': 'Not found.'})
                return
            self.send(200, result)
        except (InputError, ValueError, KeyError, TypeError) as exc:
            self.send(400, {'error': str(exc) if isinstance(exc, InputError) else 'Invalid request. Check the fields and try again.'})
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception:
            self.send(500, {'error': 'Local operation failed. Existing drafts were not silently replaced. Restart or create a new revision.'})


def serve(directory: Path, port=8717, open_browser=False):
    server = AppServer(('127.0.0.1', port), Workspace(directory))
    print(f'\n  Bot Skill Creator v{__version__}\n  {server.origin}\n  Workspace: {directory.resolve()}\n  Single-user local studio. Ctrl+C stops the server.\n', flush=True)
    if open_browser:
        webbrowser.open(server.origin)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
