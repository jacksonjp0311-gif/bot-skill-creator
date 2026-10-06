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
