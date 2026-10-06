# Provenance and continuity

The product name **Bot Skill Creator** and dual studio/harness scope were requested by
James Paul Jackson. The implementation builds on the BOT Agent Algorithm v0.1 supplied
in this conversation; it does not claim that algorithm was present in the original
46-skill collection or that its equations are mathematically novel.

## Preserved sources

| Source | Destination | SHA-256 |
|---|---|---|
| Original bot_agent.py | bsc/control.py | `8007cc5f347b6888dbda4bc52867e442429b05bb72b19d7dbbce35c437440df3` |
| Original ALGORITHM.md | docs/provenance/BOT-AGENT-ALGORITHM-v0.1.md | `5b7e5a478a6056c4e8b82c5efc4f7944125f86a1450492aae1f75ab386617312` |

Both destinations were compared byte-for-byte with the supplied source files. The
original 32 test cases were carried into tests/test_control.py with the import path
adapted from bot_agent to bsc.control. New application/compiler tests are separate.

Original source archive SHA-256: `58164247ca51d8b5d7e325fa35e2ba3786b2cc457e28854867172a98d1dda744`.

## Separate collection

The user's BOT Skills archive is not bundled into this new repository or modified by
this build. Its 46 supplied skill files remain a distinct preserved collection. The
Warehouse API and inventory-brief plan in this product are newly authored fictional
fixtures, not replacements or additions to that source collection.

## New work in this repository

The UI, compiler, model transport, OpenAPI subset import, local workspace, CLI, bridge,
export wrapper, new tests, docs and example fixtures are new implementation work.
The derivation in docs/MATH.md explains the inherited model and its assumptions; it is
not evidence of calibrated probabilities, semantic quality or measured superiority.
