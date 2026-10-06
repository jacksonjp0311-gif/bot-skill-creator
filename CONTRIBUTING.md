# Contributing

Keep one compiler behind both interfaces. Run the offline tests and document exactly
what changed. Include a minimal fixture for importer or provider changes. Never include
real credentials, private endpoints, or proprietary example records.

A useful pull request has a clear problem, the smallest change that fixes it, tests,
and updated docs for changed behavior. For UI work, include desktop and narrow-screen
captures. Preserve keyboard access and reduced-motion support. Untrusted strings render
as text, not HTML.

Do not rewrite the preserved original specification or kernel without an explicit
versioned migration and new provenance note. Do not add unrelated skills from the
separate BOT Skills collection. New examples must be marked as examples.

No performance, safety or compatibility claim should exceed its actual test evidence.
