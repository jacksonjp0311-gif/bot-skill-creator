# Use Bot Skill Creator inside a harness

Clone or unpack the COMPLETE `bot-skill-creator/` directory into a location your harness
can read. The root SKILL.md is the creator's entry point. Its scripts bootstrap relative
to their own location, so the harness does not have to change its working directory.

The exported child skill uses the Agent Skills folder format. Discovery paths and
invocation syntax belong to each harness; configure its skill root explicitly. This
release does not claim to have been exercised in every model or agent runtime.

## Python interface

```python
from pathlib import Path
from bsc.core import compile_package, validate_files, write_package
from bsc.openapi import import_document
import json

plan = json.loads(Path('examples/inventory-plan.json').read_text(encoding='utf-8'))
api = import_document(Path('examples/warehouse.openapi.json').read_text(encoding='utf-8'))
files = compile_package(plan, api, ['listInventory'])
assert validate_files(files)['ok']
# Do this only when the caller has requested this local write:
folder = write_package(Path('exports'), plan, api, ['listInventory'])
```

## CLI interface: Bash

```bash
python3 scripts/bsc.py preview --plan examples/inventory-plan.json \
  --openapi examples/warehouse.openapi.json --operations listInventory
python3 scripts/bsc.py create --plan examples/inventory-plan.json \
  --openapi examples/warehouse.openapi.json --operations listInventory --out ./exports
python3 scripts/bsc.py validate ./exports/inventory-brief
python3 scripts/bsc.py install ./exports/inventory-brief --target ./my-harness/skills
```

## CLI interface: PowerShell

```powershell
py -3 .\scripts\bsc.py preview --plan .\examples\inventory-plan.json `
  --openapi .\examples\warehouse.openapi.json --operations listInventory
py -3 .\scripts\bsc.py create --plan .\examples\inventory-plan.json `
  --openapi .\examples\warehouse.openapi.json --operations listInventory --out .\exports
py -3 .\scripts\bsc.py validate .\exports\inventory-brief
py -3 .\scripts\bsc.py install .\exports\inventory-brief --target .\my-harness\skills
```

`install` copies the whole exported skill folder and refuses an existing destination.
It does not configure or execute a harness. The destination is an example, not a claim
that a particular vendor uses that path.

## NDJSON subprocess protocol

```bash
printf '%s\n' '{"action":"preview","name":"daily-brief","brief":"Summarize provided notes into a daily brief without sending messages."}' | python3 scripts/bsc.py bridge
```

```powershell
'{"action":"preview","name":"daily-brief","brief":"Summarize provided notes into a daily brief without sending messages."}' | py -3 .\scripts\bsc.py bridge
```

One request per stdin line; one JSON response per stdout line. This is **NDJSON, not MCP**.
No unsolicited output appears on stdout in bridge mode. Supported actions:

| Action | Required input | Result |
|---|---|---|
| preview | brief or plan; optional name, openapi text, operations | Draft files and static validation; no file writes. |
| create | same as preview, plus output parent path | A newly written skill folder; never overwrites. |
| validate | path | Structure and checksum result. |
| import | document (OpenAPI JSON string) | Sanitized capability contract. |
| score | optional counts object (success, failure, unknown, cost, weight) | Declared-prior estimates. |

A response is `{"ok":true,"result":...}` or `{"ok":false,"error":"..."}`.
The protocol is local authoring; sandbox its filesystem access using the harness's
process boundary. It does not execute imported API operations or accept model signing authority.

## Integrate the reference controller

The original Python kernel is preserved in `bsc/control.py`. A trusted host can import
Action, Authority, Controller, Outcome, Skill and ToolRule. Read the original
specification and `tests/test_control.py` for explicit issue/resolve examples.

Keep Authority and the signing key outside model-accessible tools and files. Define
actual resource ACL checks and objective-specific verifiers. The database alone is not
a security boundary. See `docs/MATH.md` and `SECURITY.md` before using it for live actions.

## Persistent workspace protocol

Studio and agents share `Workspace` and the same compiler. Send NDJSON to `python -m bsc bridge`,
or save one request as JSON and run `python -m bsc workspace --request-file request.json`.
A request selects a local creator workspace directory (use a disposable directory for tests):

```json
{"action":"workspace","workspace":"./creator-state","operation":"connect","path":"/path/to/hermes","agreed":true}
```

The response includes a stable harness `id`. Supported operations:

| Operation | Additional fields | Result |
| --- | --- | --- |
| `harnesses` | none | Saved identities, context and snapshot metadata |
| `switch` | `harness_id` (or null for unbound drafts) | Active workspace |
| `context` | `harness_id`, `context` | Saved creator context; no native memory write |
| `projects` | none | Drafts in the active workspace |
| `create` | none | New draft bound to the active harness |
| `chat` | `id`, `message` | Tailored draft. Asks when a choice is unresolved. Installs when the harness check passes, and never overwrites |
| `validate` | `id` | Fresh catalog check and revision |
| `install` | `id`, `fingerprint`, `approved:true` | Revision-bound receipt, without execution |

Use the returned `install_fingerprint` as `fingerprint` only after reviewing that revision and
its `target`. Do not synthesize approval from model output. Changing the active harness does
not change the target of `chat`, `validate`, or `install` for an existing project ID.
This remains a single-user local filesystem interface, not a multi-tenant service.

Plans can include `capability_calls`, for example:

```json
{"kind":"tool","name":"memory","action":"add","inputs":{"content":"The note supplied by the user."}}
```

Each entry uses exact catalog names and maps parameter names to sources of values. These are
instruction declarations, not runtime argument values. Static validation checks the advertised
action and documented parameters. Prose counts as a call only when it names a catalog tool, skill,
action, or a path-shaped identifier, and that call is flagged when it is unsupported. The words
"write a bot skill" do not by themselves require a create, send, or delete command. A follow-up
answer keeps the original job. When the job does not choose an action, or the draft needs one
decision, the studio asks in a box and continues after the answer. An answered question is not asked again. When the answer says to ask during the job, the skill collects that fact and finishes. A package that fits is installed
under `skills/custom`, and the reply says what the skill will do and links to that folder. Natural-language
intent, runtime types, authentication and execution outcomes still require harness-side review
and enforcement. Skill commands extracted from examples can have incomplete contracts.

The local adapter stores a content-addressed snapshot with source, inspection time and
`live_verified:false`. It never imports the harness's private memory as creator context.
Only the latest five validation observations for the same snapshot are supplied to the drafter;
up to forty are retained per workspace. They do not alter the inherited control kernel or its
reliability scores. User context is sent to the selected drafting provider, so keep it free of secrets.

Existing single-harness connections migrate on first access. Legacy drafts without a stored
target remain under **Unbound drafts**; they are not silently assigned to the current harness.
Generated `skills/custom` packages are excluded from future drafting contracts to avoid using
the creator's own output as proof of additional capability.
