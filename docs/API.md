# Bring APIs without mixing up authority

There are two distinct inputs: a **model API used to draft** and an **OpenAPI contract
used to describe capabilities for the exported skill**. The latter is never executed
by this product. Import is not authentication and does not establish permissions.

## Model connection in the UI

Open the model selector in the composer or workspace settings. The local source is
Ollama at `http://127.0.0.1:11434`. When it answers, the studio fills the base URL and
model ID. Ollama needs no API key. That choice is saved for the next session and is
confirmed in the provider sheet. Other local servers are not scanned or restored.

For ChatGPT, Grok, Claude, OpenRouter, and the other remote providers, enter the exact
base URL (usually ending `/v1`), the model ID, and the API key. Press **Save key**. The
key is sealed outside the application, in `%LOCALAPPDATA%\BotSkillCreator\secrets` on
Windows (DPAPI, this user only) and in the user data directory on other systems. The
password field is cleared and the sheet confirms “Saved for the next session.” The key
is not echoed, logged, or written into browser storage, project JSON, or exports. The
next studio session loads it into process memory only when that provider is selected.
A key that is typed and used without Save key still lasts only until the server stops.
The app does not have OS-level memory protection against local administrator access.

The adapter POSTs to `<base_url>/chat/completions`. Choose the token field your provider
supports (`max_completion_tokens` or `max_tokens`), and disable JSON-object mode only
when the provider lacks that parameter. The returned text still must parse as a valid
plan JSON object. Native Anthropic Messages, native Gemini endpoints, and multimodal
attachments are not implemented. A remote GPT-5, GPT-6, or o-series model is asked
for `reasoning_effort: none` so the reply budget is used for the skill plan. If that
field is rejected, the same request is sent once without it. If the model still
returns an empty plan because the reply limit was spent, one larger request is made.

Configuration is not an authentication test. A non-success status, malformed JSON,
or timeout is reported and is not replaced with fake model output. A timed-out
request may still be billed.
Live provider calls were not tested with a paid account for this release; tests use a
local simulated compatible server.

Remote providers require HTTPS. Explicit loopback mode supports local OpenAI-compatible
servers at `127.0.0.1`, `::1` or `localhost`; it is not a LAN-wide access toggle.
Redirects are refused and ambient HTTP proxies are ignored. DNS checks are defense in
depth, not pinned-IP connections; a hardened deployment needs outbound network controls.

## Environment configuration

Bash (prompt for the key; do not commit it):

```bash
export BSC_MODEL_BASE_URL='https://YOUR-PROVIDER/v1'
export BSC_MODEL='YOUR-MODEL-ID'
read -rsp 'Model API key: ' BSC_MODEL_API_KEY; printf '\n'
export BSC_MODEL_API_KEY
python3 -m bsc serve
# After stopping the server:
unset BSC_MODEL_API_KEY
```

PowerShell:

```powershell
$env:BSC_MODEL_BASE_URL = 'https://YOUR-PROVIDER/v1'
$env:BSC_MODEL = 'YOUR-MODEL-ID'
$SecureKey = Read-Host 'Model API key' -AsSecureString
$env:BSC_MODEL_API_KEY = [System.Net.NetworkCredential]::new('', $SecureKey).Password
py -3 -m bsc serve
# After stopping the server:
Remove-Item Env:BSC_MODEL_API_KEY
```

Environment values are not a secret vault and can be visible to same-user processes.
For a keyless local server, use its actual port, enable `BSC_MODEL_LOCAL=1`, and omit
the key. Do not inherit a remote key for a different provider; clear the variable first.
`BSC_MODEL_JSON=0` disables response_format; `BSC_MODEL_TOKEN_FIELD=max_tokens` selects
the legacy token field. No model is downloaded or bundled.

CLI model drafting is explicit: `python3 -m bsc create --model --brief "..." --out exports`.
Only the supplied brief, recent chat, current draft and selected operation summaries
are sent. No other projects or the entire BOT Skills collection are sent.

## Import a business API contract

Choose “Add an API,” upload/paste a **bundled OpenAPI 3.0.x or 3.1.x JSON** document,
then select operation IDs. No API credentials are needed to import a contract.
Choose operations before drafting or refine the blueprint after changing them.

Supported: root HTTPS server, paths, common HTTP methods, operationId/summary, path
and operation parameters, JSON request schemas, response status codes, basic security
metadata, and local `$ref` references. The importer does not call external references.
Schema examples/defaults/extensions are excluded. Only selected operations are exported.
The imported source digest records the exact uploaded text; the sanitized contract is
not a byte-for-byte OpenAPI copy or a general code generator.

Explicit limits: JSON only, 1 MB document, at most 150 operations, finite nesting,
no cyclic refs, no external refs, no server variables, no per-operation servers.
OAuth/OpenID, non-JSON request bodies, response schema verification, parameter styles,
pagination and endpoint-specific serialization require a reviewed host adapter.

A missing root server is permitted with a warning; the host must supply it. Runtime
requests must be scoped to the user's authorized service/account/resources. Even a GET
operation can have effects, so all imported operations require host approval by default.

The example Warehouse API uses a reserved example domain and is deliberately fictional.
It cannot provide real inventory data.

## Data paths

- Local drafts/chat: `~/.bot-skill-creator/projects/` (or explicit workspace).
- Local exported ZIPs: `~/.bot-skill-creator/exports/`.
- Artifact issue/resolve ledger: `~/.bot-skill-creator/ledger.sqlite3`.
- Model key: sealed outside the app after Save key, or an explicitly supplied environment variable. Process memory holds it only while the studio is running. Not in drafts or exports.
- Imported business API credentials: not collected; only future environment-variable names.

Delete or back up your own workspace deliberately. Drafts may contain private business
information, even when no credential patterns are detected. Review exports before sharing.
