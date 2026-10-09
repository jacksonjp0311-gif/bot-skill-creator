"""Single-user loopback web app. Deliberately refuses public bind addresses."""
from __future__ import annotations
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
import sys
import threading
import time
import urllib.request
from urllib.parse import urlsplit, parse_qs
import webbrowser
from . import __version__, core
from .security import InputError
from .discover import discover_local_models
from .workspace import Workspace

WEB = Path(__file__).parent / 'web'
_CLIENT = re.compile(r'^[A-Za-z0-9_-]{8,80}$')
ASSETS = {'/': ('index.html', 'text/html; charset=utf-8'),
          '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
          '/theme.js': ('theme.js', 'text/javascript; charset=utf-8'),
          '/style.css': ('style.css', 'text/css; charset=utf-8'),
          '/favicon.svg': ('favicon.svg', 'image/svg+xml')}

class PagePresence:
    """Pages that still have the studio open. Closing the last one ends a launched server."""

    def __init__(self):
        self._lock = threading.Lock()
        self._seen = {}
        self.armed = False

    def beat(self, client_id):
        if not isinstance(client_id, str) or not _CLIENT.fullmatch(client_id):
            raise InputError('Missing studio page.')
        now = time.monotonic()
        with self._lock:
            self._seen[client_id] = now
            self.armed = True
            if len(self._seen) > 20:
                for key in sorted(self._seen, key=self._seen.get)[:-20]:
                    del self._seen[key]

    def live(self, now, idle):
        with self._lock:
            expired = [key for key, seen in self._seen.items() if now - seen > idle]
            for key in expired:
                del self._seen[key]
            return bool(self._seen), self.armed


class AppServer(ThreadingHTTPServer):
    # An exclusive bind so a second launch can see that the studio is already up.
    allow_reuse_address = False
    daemon_threads = True
    def __init__(self, addr, workspace):
        if addr[0] != '127.0.0.1':
            raise ValueError('Only 127.0.0.1 is supported. Use a private local session, not a public deployment.')
        self.workspace = workspace
        self.token = secrets.token_urlsafe(32)
        self.until_close = False
        self.presence = None
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
                scope = parse_qs(parsed.query, keep_blank_values=True)
                projects = (self.server.workspace.list(scope['harness_id'][0] or None)
                            if 'harness_id' in scope else self.server.workspace.list())
                self.send(200, {'version': __version__, 'token': self.server.token,
                    'until_close': self.server.until_close,
                    'projects': projects, 'provider': self.server.workspace.provider_info(),
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
            elif path == '/api/harness':
                self.boundary(write=True)
                self.send(200, self.server.workspace.harness_profile())
            elif path == '/api/harnesses':
                self.boundary(write=True)
                self.send(200, self.server.workspace.harness_list())
            elif path == '/api/draft-phase':
                self.boundary(write=True)
                project_id = parse_qs(parsed.query).get('id', [''])[0]
                self.send(200, self.server.workspace.draft_status(project_id))
            else:
                self.send(404, {'error': 'Not found.'})
        except InputError as exc:
            self.send(403, {'error': str(exc)})
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
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
                result = ws.create(data['harness_id']) if 'harness_id' in data else ws.create()
            elif path == '/api/projects/delete':
                result = ws.delete(data.get('id'))
            elif path == '/api/chat':
                result = ws.chat(data.get('id'), data.get('message'))
            elif path == '/api/import':
                result = ws.import_api(data.get('id'), data.get('document'))
            elif path == '/api/select':
                result = ws.select(data.get('id'), data.get('selected_ids'))
            elif path == '/api/plan':
                result = ws.edit_plan(data.get('id'), data.get('plan'))
            elif path == '/api/validate':
                result = ws.validate(data.get('id'))
            elif path == '/api/install':
                result = ws.install(data.get('id'), data.get('fingerprint'), data.get('approved'))
            elif path == '/api/open-skill':
                result = ws.open_installed(data.get('id'))
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
            elif path == '/api/harness/find':
                result = ws.find_harness(data.get('path'))
            elif path == '/api/harness/accept':
                result = ws.accept_harness(data.get('path'), data.get('agreed'))
            elif path == '/api/harness/remove':
                result = ws.remove_harness()
            elif path == '/api/harness/switch':
                result = ws.switch_harness(data.get('id'))
            elif path == '/api/harness/context':
                result = ws.set_harness_context(data.get('id'), data.get('context'))
            elif path == '/api/presence':
                if self.server.until_close and self.server.presence is not None:
                    self.server.presence.beat(data.get('client'))
                result = {'ok': True, 'until_close': bool(self.server.until_close)}
            else:
                self.send(404, {'error': 'Not found.'})
                return
            self.send(200, result)
        except (InputError, ValueError, KeyError, TypeError) as exc:
            self.send(400, {'error': str(exc) if isinstance(exc, InputError) else 'Invalid request. Check the fields and try again.'})
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        except Exception:
            self.send(500, {'error': 'Local operation failed. Existing drafts were not silently replaced. Restart or create a new revision.'})


def _studio_is_open(port):
    url = f'http://127.0.0.1:{port}/'
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.status == 200 and b'Bot Skill Creator' in response.read(4000)
    except Exception:
        return False


def _watch_page(server, presence, idle, startup_grace):
    started = time.monotonic()
    while True:
        time.sleep(0.4)
        now = time.monotonic()
        live, armed = presence.live(now, idle)
        if (armed and not live) or (not armed and now - started >= startup_grace):
            try:
                server.shutdown()
            except Exception:
                return
            return


def serve(directory: Path, port=8717, open_browser=False, until_close=None, idle_seconds=8.0, startup_grace=45.0, quiet=None):
    """Serve the studio on 127.0.0.1.

    A normal launch opens the browser and keeps the process only while a studio page is open.
    Pass until_close false to leave a console server up until Ctrl+C.
    """
    if until_close is None:
        until_close = bool(open_browser)
    if quiet is None:
        quiet = bool(open_browser)
    try:
        server = AppServer(('127.0.0.1', port), Workspace(directory))
    except OSError:
        if open_browser and _studio_is_open(port):
            webbrowser.open(f'http://127.0.0.1:{port}/')
            return
        print(f'Port {port} is already in use. Close the other program, or choose another port.', file=sys.stderr, flush=True)
        raise SystemExit(1)
    server.until_close = bool(until_close)
    if server.until_close:
        server.presence = PagePresence()
        threading.Thread(target=_watch_page, args=(server, server.presence, idle_seconds, startup_grace), daemon=True).start()
    if not quiet:
        print(f'\n  Bot Skill Creator v{__version__}\n  {server.origin}\n  Workspace: {directory.resolve()}\n  Single-user local studio. Ctrl+C stops the server.\n', flush=True)
    if open_browser:
        webbrowser.open(server.origin)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
