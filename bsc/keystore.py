"""Save provider keys outside the application, for this Windows user only.

The folder is not the project, the export, or the browser. On Windows the key
is sealed with DPAPI. Elsewhere it is sealed with a user-only key file. The
plaintext is never written into a project draft.
"""
from __future__ import annotations
import ctypes
import hashlib
import hmac
import json
import os
from ctypes import wintypes
from pathlib import Path
import subprocess
from .security import InputError, text

PROVIDERS = frozenset({'openai', 'grok', 'claude', 'openrouter', 'gemini', 'mistral', 'groq', 'custom'})


def default_secrets_dir() -> Path:
    local = os.environ.get('LOCALAPPDATA')
    if local:
        return Path(local) / 'BotSkillCreator' / 'secrets'
    return Path.home() / '.local' / 'share' / 'bot-skill-creator' / 'secrets'


class Keystore:
    def __init__(self, directory: Path | None = None):
        self.path = Path(directory) if directory is not None else default_secrets_dir()

    def list_providers(self):
        if not self.path.is_dir():
            return []
        return sorted(name.stem for name in self.path.glob('*.key') if name.stem in PROVIDERS)

    def has(self, provider):
        return provider in PROVIDERS and (self.path / f'{provider}.key').is_file()

    def save(self, provider, api_key):
        if provider not in PROVIDERS:
            raise InputError('Choose a remote provider before saving a key.')
        if not isinstance(api_key, str) or not api_key.strip():
            raise InputError('Enter the key, then save it.')
        secret = text(api_key, 'API key', 8000)
        self._prepare()
        payload = json.dumps({'v': 1, 'provider': provider, 'api_key': secret}, ensure_ascii=False).encode()
        target = self.path / f'{provider}.key'
        self._write(target, _seal(payload, self._seal_key()))
        return {'saved': True, 'provider': provider, 'confirmation': 'Saved for the next session.'}

    def load(self, provider):
        if provider not in PROVIDERS:
            return ''
        target = self.path / f'{provider}.key'
        if not target.is_file():
            return ''
        try:
            data = json.loads(_open_seal(target.read_bytes(), self._seal_key()).decode())
        except (OSError, ValueError, json.JSONDecodeError):
            return ''
        if not isinstance(data, dict) or data.get('provider') != provider:
            return ''
        key = data.get('api_key')
        return key if isinstance(key, str) else ''

    def save_local(self, provider):
        """Remember the Ollama model. This file has no API key."""
        if not isinstance(provider, dict) or not is_ollama_url(provider.get('base_url', '')):
            raise InputError('Only an Ollama model on this machine can be remembered.')
        model = provider.get('model')
        if not isinstance(model, str) or not model.strip():
            raise InputError('Choose an Ollama model before remembering it.')
        self._prepare()
        body = json.dumps({
            'base_url': provider['base_url'], 'model': model,
            'token_field': provider['token_field'], 'json_mode': provider['json_mode'],
        }, ensure_ascii=False)
        self._write(self.path / 'ollama.json', body.encode())

    def local_preference(self):
        target = self.path / 'ollama.json'
        if not target.is_file():
            return None
        try:
            data = json.loads(target.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        base = data.get('base_url')
        model = data.get('model')
        if not isinstance(base, str) or not isinstance(model, str) or not is_ollama_url(base):
            return None
        return {'base_url': base, 'model': model,
                'token_field': data.get('token_field') if data.get('token_field') in {'max_tokens', 'max_completion_tokens'} else 'max_tokens',
                'json_mode': data.get('json_mode') is True}

    def _prepare(self):
        self.path.mkdir(parents=True, exist_ok=True)
        if os.name == 'nt':
            user = (os.environ.get('USERDOMAIN') or '') + '\\' + (os.environ.get('USERNAME') or '')
            if user != '\\':
                flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
                subprocess.run(['icacls', str(self.path), '/inheritance:r', '/grant:r', user + ':(OI)(CI)F'],
                               capture_output=True, check=False, creationflags=flags)
        else:
            os.chmod(self.path, 0o700)

    def _seal_key(self):
        if os.name == 'nt':
            return b''
        target = self.path / 'seal.key'
        if not target.is_file():
            self._write(target, os.urandom(32))
        return target.read_bytes()

    def _write(self, target, payload):
        temp = target.with_suffix(target.suffix + '.tmp')
        with temp.open('wb') as handle:
            if os.name != 'nt':
                os.chmod(temp, 0o600)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
        if os.name != 'nt':
            os.chmod(target, 0o600)


def is_ollama_url(value):
    from urllib.parse import urlsplit
    if not isinstance(value, str):
        return False
    parsed = urlsplit(value)
    return parsed.hostname in {'127.0.0.1', 'localhost', '::1'} and parsed.port == 11434


def _seal(payload, key):
    if os.name == 'nt':
        return b'DPAPI1' + _dpapi(payload, protect=True)
    nonce = os.urandom(16)
    stream = _keystream(key, nonce, len(payload))
    body = bytes(left ^ right for left, right in zip(payload, stream))
    mac = hmac.new(key, nonce + body, hashlib.sha256).digest()
    return b'SEAL1' + nonce + mac + body


def _open_seal(blob, key):
    if blob.startswith(b'DPAPI1'):
        return _dpapi(blob[6:], protect=False)
    if not blob.startswith(b'SEAL1') or len(blob) < 6 + 16 + 32:
        raise ValueError('unrecognized key file')
    nonce, mac, body = blob[6:22], blob[22:54], blob[54:]
    if not hmac.compare_digest(mac, hmac.new(key, nonce + body, hashlib.sha256).digest()):
        raise ValueError('key file failed its check')
    stream = _keystream(key, nonce, len(body))
    return bytes(left ^ right for left, right in zip(body, stream))


def _keystream(key, nonce, size):
    output = b''
    counter = 0
    while len(output) < size:
        output += hmac.new(key, nonce + counter.to_bytes(4, 'big'), hashlib.sha256).digest()
        counter += 1
    return output[:size]


class _Blob(ctypes.Structure):
    _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_byte))]


def _dpapi(data, *, protect):
    buffer = ctypes.create_string_buffer(data)
    incoming = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    outgoing = _Blob()
    function = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    # CRYPTPROTECT_UI_FORBIDDEN: never pop a credential dialog from the studio.
    if not function(ctypes.byref(incoming), None, None, None, None, 0x1, ctypes.byref(outgoing)):
        raise OSError('The local key protector could not finish.')
    try:
        return ctypes.string_at(outgoing.pbData, outgoing.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(outgoing.pbData)
