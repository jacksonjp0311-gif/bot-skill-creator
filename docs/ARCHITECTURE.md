# One engine, two interfaces

```text
Human in browser                Agent / developer
      │                         CLI / Python / NDJSON
      └───────────────┬─────────────────┘
                      ▼
            Draft plan + selected capability contract
                      │
            Deterministic compiler (core.py)
                      │
         Fixed workflow rules + static validation
                      │
           Preview / local human review
                      │
     Revision fingerprint → Controller → artifact ZIP
                      │
           Portable skill folder for a harness
                      │
      [future host owns external execution and proofs]
```

The model adapter can propose text and plan fields; it cannot alter compiler-owned
approval requirements, enable automatic execution or add capabilities to the selected
contract. OpenAPI import only reads a local document. Model API requests are the only
outbound network calls performed by the creator, and only when explicitly configured.

## Persistent state

The workspace stores one project JSON per draft and one SQLite export ledger. A project
contains chat, sanitized API contract, selected operation IDs, plan and revision. A file
save uses a temporary file, flush/fsync and replace. The app's lock serializes mutations
within one process; multiple independently launched servers must not share a workspace.
There is no multi-tenant concurrency, database migration framework or cloud sync.

An export fingerprint covers project ID, revision and every previewed file hash. The
review confirmation returns that fingerprint. Changed revisions fail the gate. The
reference controller records one issue per logical export. Artifact bytes are written,
read back and checked before its SUCCESS receipt is recorded. A completed repeated export
returns the existing file; an unresolved export is not blindly replayed.

The draft compiler is deterministic for the same plan, selected contract, template,
math reference and product version. ZIP entry timestamps are fixed to remove clock noise.
Model drafting is not deterministic and should not be represented as such.

## Boundary inventory

| Boundary | Owner |
|---|---|
| Brief and imported documentation | Untrusted content |
| Candidate procedure | Human/model proposal |
| API selection | Explicit local user/caller choice |
| Fixed export schema and workflow | Compiler |
| Local export approval | Current single-user UI or explicit CLI write |
| HMAC Authority | In-process trusted host; not a model tool |
| Business API execution and resource ACLs | Future harness, not this creator |
| Live evidence verification | Future task-specific verifier |

The local trust model is not protection from malicious same-user code. Hardened execution
requires OS/process isolation and a separately privileged controller.
