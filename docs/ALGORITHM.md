# The algorithm, in human terms

**A skill is a repeatable decision procedure—not just a clever prompt.**

Bot Skill Creator turns a brief into a portable contract. It uses the supplied BOT Agent
Algorithm v0.1 as its control template, preserving its distinction between proposals,
permissions, execution identity and verified outcomes. It does not invent a live executor.

## The creation loop

| Stage | What the creator does | What the human can inspect |
|---|---|---|
| Observe | Read the brief and required inputs. | Goal, description, assumptions. |
| Select | Include only explicitly selected API operation IDs. | Selected methods and paths. |
| Load | Read the template and sanitized API contract. | Source digest and file preview. |
| Gate | Validate draft structure and bind export approval to its exact revision. | Workflow, constraints and review fingerprint. |
| Issue | Record the local archive issue before writing it. | Stable project/revision export identity. |
| Verify | Re-read ZIP entries and compare their hashes. | Static validation and artifact evidence. |
| Record | Keep local drafts and the export receipt. | Local project files and ledger. |

### Example
“I want an inventory skill that shows what needs restocking, but never places orders.”

The user imports a warehouse contract and chooses `listInventory`, leaving
`createPurchaseOrder` unselected. The compiler produces an inventory brief procedure,
an API contract with only that selected capability, and requirements for the future host
to verify quantities against source records. It does not call either operation.

The person previews and exports the files. That export's SUCCESS means the archive
was created and its bytes verified. It says nothing about a warehouse request having run.

## Proposed external execution loop

```text
observe the request and state
resolve the next verifiable objective
retrieve reviewed bindings for that same objective
filter unavailable inputs, tools, dependencies and context budgets
rank eligible alternatives when comparable outcome evidence exists
load unchanged instructions and selected dependencies
prepare exact action and state fingerprint
host checks scope, budget, authenticity and expiry of approval
persist ISSUE before external dispatch
verify actual postconditions from evidence
record SUCCESS, FAILURE or UNKNOWN
continue, await a receipt, ask for input, or stop
```

The exported skill instructs this behavior. Its host must implement the privilege
boundaries. A prompt cannot grant permission, store secrets safely, or prove an action
happened merely by saying so.

## The small equation behind routing

For the same binding, version, objective and context:

$$\hat\theta=(S+1)/(S+F+U+3),\qquad score=\hat\theta-\lambda c.$$

S is verified success, F is verified failure, U is a terminal unknown result, and c is
a normalized declared cost. No history means a declared prior of 1/3—not measured quality.
Permission is a gate, not a score penalty. The creator's calculator demonstrates this
estimate; it does not train a model or rank your new skill as “better” without evidence.

Read [the mathematical derivation](MATH.md) for the coherent Dirichlet model, its
assumptions, variance, q/μ split, action fingerprints and limits of local at-most-once issue.

## What is implemented and what is not

Implemented: local drafting, provider JSON transport, plan validation, OpenAPI subset
import, operation selection, deterministic compilation, revision-bound export approval,
local issue/resolve control, ZIP verification, saved drafts and portable output.

Host responsibilities: actual business API execution, token custody, OAuth, resource
ACLs, rate limits, provider idempotency, live-state checks, execution watchdogs and
objective-specific verification. Autonomous skill promotion is not implemented.
