# Changelog

## 2026-10-08 · Harness workspace verification

- Persist separate harness identities, capability snapshots, creator context and validation feedback.
- Bind drafts to their original harness across switches and restarts.
- Require explicit revision-bound installation; reject stale snapshots, unknown actions and missing inputs.
- Expose the shared workspace workflow through studio, CLI and NDJSON.
- Narrow template routing to requested capabilities and exclude forbidden actions and unrelated tools.
- Keep static checks distinct from live execution evidence.

## 0.1.0 · 2026-10-06

Initial local release of Bot Skill Creator.

- macOS-inspired browser studio with chat, API import, operation selection, draft library,
  live file preview, editable plans, math explorer and reviewed ZIP export.
- Dependency-free Python CLI, JSON bridge and importable compiler.
- Optional compatible model API. Remote keys can be sealed outside the app; offline template mode remains.
- OpenAPI 3.0/3.1 JSON subset import without business API execution.
- Shared deterministic skill template and artifact integrity checks.
- Original BOT Agent Algorithm kernel and specification preserved with provenance.
- Human/agent docs, detailed math, Bash/PowerShell launchers and reproducible tests.
- Studio fits the browser window, with a persisted dark mode and Enter-to-build chat.
- API connections opens as provider sections for ChatGPT, Grok, Claude, OpenRouter, and other compatible endpoints.
- My skills can open a draft, read the package, export the ZIP, or delete the local draft.
- The skill studio finds local model servers and loads the endpoint when a model is selected.
- Light mode uses a deeper purple so labels, the active section, and buttons stay readable.
- ChatGPT lists the current chat models. While offline, the studio keeps looking for Ollama and fills the endpoint when one model answers. Fetch checks immediately.
- Save key seals a remote provider key outside the app for the next session. Ollama needs no key and confirms that its model choice was saved. Other local servers are not selected.
- Sending a chat message shows it immediately, then a working line until the draft returns. A stopped request keeps the status and puts the unsent text back.
- An accepted harness teaches the drafter each tool's purpose, actions, and required inputs, and each skill's one-line summary. The model writes the skill for that application. Cleanup does not invent the procedure.
- A draft is woven into the skills that already do the job. The model receives their documented commands and required inputs, rewrites the procedure once if those calls are missing, and the sandbox refuses a package that only names a skill.
- Each draft rereads that harness's memory and nexus first. The working line says Analyzing harness, then the studio writes the skill, checks the package in a sandbox, and offers a reviewed install under skills/custom. An existing skill is not overwritten, and the skill is not run.
- While a draft is running, the chat shows an orbit, a wave, and a traveling light beside the working line.
- The README opens with light-mode and dark-mode pictures of an empty studio. No personal drafts or keys are part of the repository.
- Saved keys can be opened again on macOS and Linux. The portable seal header is read at its real length.
- Running the studio opens the local page and keeps the server only while that page is open. `bsc serve` does this by itself. The launcher does not leave a console waiting.
- An accepted harness is included when a skill is drafted. The request does not have to name the skills or tools that are already in that harness.
- `install.ps1` and `install.sh` put the studio logo on the desktop. Clicking it opens the local studio and leaves it up while that page is open.
- The desktop icon is a classic Windows bitmap, so Explorer draws the logo instead of a blank shortcut.

Known release boundaries are documented in README.md and SECURITY.md.
