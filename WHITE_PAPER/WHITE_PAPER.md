# Bot Skill Creator: a compiler for inspectable agent procedures

**Version 0.1.0 · Design report, not a validated performance study**

## Abstract

Bot Skill Creator separates skill authoring from execution authority. A human or model
produces a structured plan. A deterministic compiler combines it with explicitly selected
API operations and fixed control-loop requirements. A local browser studio and an agent
CLI emit the same portable folder. The supplied BOT Agent Algorithm v0.1 provides a
reference control kernel and the mathematical distinction between verifiable outcomes
and conditional success. This release demonstrates artifact production, not autonomous
execution of the described business workflows.

## Motivation

A reusable procedure should preserve intent, scope, prerequisites and evidence criteria,
not merely an unconstrained prompt. Human authors need to inspect what a bot will read.
Agents need a stable authoring interface without a browser dependency. Neither should
mistake an API schema for authenticated access or a static validator for a task verifier.

## Construction

Let D be the user/model draft, A the sanitized API contract, L the selected operation IDs,
and T the versioned compiler template. The compiler C produces files F=C(D,A,L,T).
It validates D's structure, requires L to be a subset of imported IDs, rejects unsupported
reference shapes, and writes workflow boundaries that draft fields cannot disable.
Determinism is conditioned on all source/reference versions, not on a model's generation.

The browser presents H(project, revision, hashes(F)). Local approval must match it before
artifact issue. The export controller persists issue before ZIP creation, then verifies
the ZIP's contents. Its authenticated receipt asserts artifact integrity, not live success.

## Mathematical substrate

The reference outcome model separates Q, probability of obtaining a verified terminal
outcome, from M, probability of success conditional on verification. With a coherent
Dirichlet posterior, E[Q]E[M]=E[p_success]. Unknown outcomes affect Q without masquerading
as verified failures in M. The derivation and assumptions are in `../docs/MATH.md`.

Selection scores rank only comparable eligible bindings. Scope and authorization are
hard constraints, not compensable penalties. This release exposes the estimator and
preserves the reference router; it does not collect real execution histories to claim
adaptive superiority.

## Boundaries and evaluation

The local software is a single-user process, not a hostile multi-tenant runtime. The
future harness must provide independently enforced resource ACLs, secret custody,
external execution, idempotency, live-state checks and evidence verifiers. Markdown,
JSON schema, content hashes and host signatures each solve different limited problems.
None alone provides end-to-end safety or truth.

The evaluation in this release comprises synthetic controller tests, compiler and
importer tests, a simulated model server, local HTTP tests, CLI round trips and mounted
Chromium UI interaction checks. Comparative agent completion rates remain unmeasured.

## Next research questions

Measure whether instruction-only use and host-integrated use improve verified completion
at acceptable cost. Separate blocking, semantic failure, transport uncertainty and actual
unauthorized effects. Evaluate on held-out workflows with independently checked evidence.
Never promote a procedure merely because its own model labels it successful.

## Continuity

The original algorithm specification and kernel hashes are recorded in `../docs/PROVENANCE.md`.
The user's separate 46-skill collection is neither bundled nor modified. The fictional
inventory example belongs to this product's tests, not that preserved collection.
