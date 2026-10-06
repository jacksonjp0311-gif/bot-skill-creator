# Context packet for the next agent

Product: Bot Skill Creator. Release: 0.1.0. One repo, browser studio plus CLI/NDJSON.
Mission: turn custom intent and selected API contracts into portable, inspectable skills.

## Read order

README.md → SKILL.md → docs/ALGORITHM.md → docs/ARCHITECTURE.md.
For equations and proof limits, read docs/MATH.md. Original lineage is in docs/PROVENANCE.md.

## Implemented

Deterministic compiler, bounded plan schema, read-only OpenAPI subset importer, compatible
model JSON transport, local project persistence, reviewed artifact export through the
preserved issue/resolve kernel, CLI/NDJSON, checksum verifier and native-looking browser UI.

## Not implemented

Public SaaS, multi-tenant authorization, native packaged app, business-API execution,
OAuth setup, actual model training, calibrated routing histories, autonomous promotion,
or a universal harness adapter. NDJSON is not MCP. Template mode is not model inference.

## Invariants

Do not modify the separate original BOT Skills archive. Do not expose host signing
operations to the model. Do not persist or export keys. Do not claim static checks establish
live correctness. No auto-retry after an unknown external outcome. No silent output overwrite.

## Next work

Use actual test transcripts. Re-run from an extracted release. Preserve provenance while
versioning derived changes. Test a real model provider only with the owner's configured
credentials and requested scope; never invent an API connection or a successful deployment.
