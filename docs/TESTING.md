# Testing and honest release evidence

## Required offline tests

`python3 -m unittest discover -s tests -v` (Bash), or
`py -3 -m unittest discover -s tests -v` (PowerShell).

The original algorithm's 32 tests are retained with only their module import adjusted.
The new suite tests OpenAPI import, plan validation, compiler-owned controls, deterministic
ZIP generation, file preservation, context-limited operation selection, local persistence,
exact-revision export approval, duplicate/restarted exports, HTTP boundaries and the
compatible model wire contract against a local simulated server.

The actual run transcript, interpreter and platform are recorded in `docs/test-results.txt`.
The provided CI matrix is a configuration, not evidence that all matrix jobs already ran.

## Manual local UI check

Launch the studio; import the example API; select only `listInventory`; create the
inventory brief; edit its plan; inspect the workflow; approve a ZIP; run the exported
`scripts/validate.py`; reopen the saved draft. A key typed into the provider sheet and
not saved must disappear when the process stops. A key stored with Save key must come
back only inside process memory for that provider, never inside the project or an export.

## Optional automated browser check

Install Playwright and its Chromium browser in your development environment, or point
`BSC_CHROMIUM` at an approved existing Chromium executable. The application itself does
not need either. Run `python scripts/browser_smoke.py`.

For reproducibility in managed environments, this smoke script mounts the application's
unchanged HTML/CSS/JS into a blank page and implements fetch with a Playwright-to-Python
bridge to a real isolated local HTTP server. It exercises actual UI events and server
round trips. It does **not** prove direct browser networking or CSP enforcement. The
HTTP suite checks the server's origin/Host/token handling separately.

Screenshots in `docs/assets` are captured from that implemented interface with a fictional
API and example data; they are not AI-generated mockups or pictures of a deployed SaaS.
`browser-results.json` lists the checks and exclusions.

## Not established by these tests

Live paid-model compatibility, exact provider billing, external API correctness,
real OAuth, semantic quality of generated plans, universal harness compatibility,
end-to-end security, model improvement, production scalability, or native platform
launch behavior. Windows and macOS need their actual CI/manual runs.

## Reproducibility before shipping

Run the tests from the extracted release, not only the working folder. Run the example
creator from a path with spaces. Check every relative documentation link. Verify the
release manifest and original provenance hashes. Inspect screenshots for overflow and
render model or user strings as text, never trusted HTML.
