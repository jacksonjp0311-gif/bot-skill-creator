# BOT Agent Algorithm v0.1

**Status:** proposed control algorithm with a runnable, offline-tested Python reference kernel. Not a live browser agent, not a new model, and not a claim of mathematical novelty or measured superiority.

## Purpose

Operate a bot's skill library through a bounded loop:

**Observe → select → load → gate → issue → verify → record → continue or stop.**

The model proposes a plan. The trusted host controls authorization, execution, and evidence verification. The skill library supplies procedural guidance, not authority. Original user-supplied skill files remain read-only. Derived routing metadata and observations belong outside those files.

## 1. Inputs and separation of responsibilities

Each run pins a reviewed policy/catalog release and a context scope. The scope should distinguish the task class, model version, runtime/adapter version, and materially different environments. Do not pool unrelated contexts to manufacture a success rate.

A reviewed skill-step binding consists of:

- the skill identifier, version, and original-file hash;
- the specific verifiable objective it implements;
- the tool/capability requirements and pinned supporting dependencies;
- a planner/executor adapter and a separately approved evidence verifier;
- stop conditions, side-effect classification, and resource bounds.

One binding is an alternative way of achieving the SAME next objective. A checkout-placement binding does not compete with a menu-reading binding. Supporting authentication instructions are dependencies, not substitute goal candidates.

The reference `Skill` class describes that binding. `Action` describes one invocation. It can correspond to a bounded subgoal rather than one UI click. If its adapter performs several primitive steps, the host must gate every material side effect. Primitive click acknowledgements are not proof that a multi-step objective succeeded.

## 2. Eligibility before ranking

For goal stage g and observed context x, form the candidate set:

F(x,g) = { s : reviewed(s) AND objective(s)=g AND capabilities_available(s)
                 AND inputs_grounded(s,x) AND dependencies_valid(s)
                 AND relevant_context_fits(s) }.

Permissions for future stages are NOT prerequisites for starting an authorized read-only stage. Lack of checkout approval must not prevent researching an item. Conversely, research authorization never authorizes a checkout.

Missing capabilities/inputs produce a typed blocked or input-needed result. No eligible binding produces NO_ELIGIBLE_SKILL. Do not fabricate a tool, install software, expand access, or silently execute skill snippets as a workaround.

Read compact catalog metadata first. Load only the selected binding's original instructions and necessary dependencies. Count actual tokens with the intended model's tokenizer, including wrappers, tool schemas, evidence, and working/output reserves. Do not truncate away safety/stop rules to satisfy the limit. Reject dependency cycles and hash changes.

The compact reference implements reviewed-key, objective, and tool filtering. Full dependency resolution, token accounting, and source-load sequencing are host responsibilities.

## 3. Evidence-based routing score

For the SAME binding/version, objective, and context scope, project these counts from terminal records:

S = verified successes
F = verified failures
U = attempts closed with an unknown outcome

Blocked proposals and active IN_FLIGHT attempts are not observations in these counts. A process exit code or a worker's unsupported claim is not a terminal outcome.

Choose explicit symmetric pseudocounts of one in each category (a Dirichlet(1,1,1) modeling assumption). Define:

q = (S + F + 2) / (S + F + U + 3)
mu = (S + 1) / (S + F + 2)
theta = q * mu = (S + 1) / (S + F + U + 3)

Here q estimates whether execution will yield a verifiable outcome; mu estimates success conditional on verification; theta estimates verified success. Unknown outcomes lower q but do not enter mu as verified failures. These are declared-prior planning estimates, not calibrated empirical guarantees. With no history, theta is 1/3 by construction.

For each eligible candidate, require a declared normalized cost c in [0,1]. Select:

s* = argmax_s [ theta(s) - lambda * c(s) ]

lambda >= 0 is a fixed policy parameter; 0.15 is an illustrative default, not an optimized constant. Cost estimates must share a stated scale across candidates. Missing estimates are not assumed to mean zero cost. Ties break deterministically by binding key.

Permission is never a score penalty. No amount of success evidence buys permission. Default mode has no live exploration bonus. Evaluate new routes on offline fixtures or explicitly authorized trials. Observational routing histories alone do not establish which route would have been best on untried tasks.

## 4. Exact action preparation and authorization

A proposed action freezes:

(run ID, stable step ID, binding/version, objective, tool, canonical arguments,
 relevant observed-state fingerprint, approved verifier ID).

Its action ID is derived from run ID + stable logical step ID. Its approval fingerprint covers the entire frozen proposal, including its target, total, currency, recipient, options, and preconditions where relevant. The reference canonicalization is Python-specific; a multi-language deployment must standardize an encoding rather than assume every serializer agrees.

Immediately before dispatch, the HOST checks:

- the current policy and binding are the pinned, approved ones;
- the actual resource/tenant/recipient is in the user's authorized scope;
- the tool is allowed and available;
- required inputs and source/dependency hashes are valid;
- the relevant live state matches the proposed state;
- the next action fits action-count, quota, and deadline bounds;
- any required exact-action approval is authentic and unexpired;
- this logical operation has not already been issued.

A changed price, recipient, or target requires a new proposal and, where applicable, new approval. State checks must be done at the actual execution boundary. A fingerprint alone cannot eliminate a change between reading state and sending a request; use provider conditional/versioned operations where available and otherwise revalidate and stop on ambiguity.

No model-provided `safe=true`, claimed permission, or self-issued approval satisfies the gate. Reference Authority signing methods are TRUSTED HOST operations, not tools to expose to the model.

## 5. Durable issue and event-driven continuation

Atomically reserve resources and persist ISSUE before the executor receives the action. The reference returns DISPATCH only for the first issue of the logical action in its database. The host executes only on that return value. Repeated issue calls return IN_FLIGHT or the already recorded terminal status, never another dispatch decision. Changed arguments under the same logical action ID produce a conflict.

Yield control while the worker is active; preserve worker identity, active skill/version, current objective, evidence references, and the next required transition. Resume the same live worker for the same work unit unless its session is lost. The reference tracks IN_FLIGHT, but worker/session management is an adapter responsibility.

A crash after ISSUE but before execution is deliberately ambiguous. Do not automatically replay. Reconcile through a read-only external status check, or close UNKNOWN. The database provides local at-most-once dispatch decisions, NOT exactly-once execution at an external service. Provider idempotency keys/operation IDs and reconciliation are still necessary.

The host needs an external timeout/watchdog and actual token/cost metering. The kernel checks the deadline before new issues and reserves declared integer quota units. It does not interrupt network calls, cancel remote effects, or enforce a provider's monetary bill.

## 6. Verification and terminal outcomes

The approved host verifier binds evidence to the issued action fingerprint and checks the objective's actual postcondition.

- SUCCESS: evidence establishes the intended postcondition.
- FAILURE: evidence establishes the intended postcondition did not hold.
- UNKNOWN: the evidence cannot establish what happened.

An exception after a request may have reached a server is not automatically FAILURE. A blank confirmation screen is not proof that nothing happened. UNKNOWN halts the reference run; it is never automatically retried. A separate read-only reconciliation can establish external state for a newly authorized continuation.

Receipts are signed by a trusted host authority in the reference. Their signature authenticates the host statement, not the external truth. The host must actually implement the verifier; using another model's ungrounded assertion is not independent verification.

Record a terminal result once. Duplicate identical receipts are no-ops. Conflicting terminal results fail closed. UNKNOWN remains the historical result for that attempt; later reconciliation should be a distinct evidence event rather than silent relabeling.

## 7. Learning without self-authorization

Terminal observations may inform routing estimates for future runs within the already approved policy. To keep an in-flight run reproducible, snapshot the scoped statistics at its start and use that same map until it ends. The reference returns scoped statistics and accepts a supplied history map; the host must make and pin that snapshot.

Behavioral changes are proposal-only:

observation → candidate lesson → representative offline tests → held-out evaluation
→ authorized review → separately versioned activation.

Do not automatically modify original skills, policy, permissions, verifiers, source provenance, or approval records. Do not automatically convert inferred preferences into user memory. Compare candidates with a fixed baseline, not just their own self-reported success. Keep prior approved versions available. This candidate-review/promotion workflow is specified here, not implemented by the compact kernel.

## 8. Full host-loop pseudocode

```text
START goal under a pinned policy, catalog, context scope, and finite budget
history_snapshot := scoped terminal observations at run start

ON each trusted observation or worker result:
    if global goal verifier proves completion:
        return VERIFIED_SUCCESS with evidence
    if exhausted or unresolved terminal side effect:
        return STOPPED or UNKNOWN with current evidence
    if a worker is still active:
        return WAIT_FOR_RECEIPT                  # no second dispatch

    stage := resolve the next verifiable objective from goal and evidence
    candidates := retrieve reviewed bindings for that same objective
    feasible := validate inputs, tools, dependencies, context, and scope
    if feasible is empty:
        return NO_ELIGIBLE_SKILL with the exact missing prerequisites

    binding := deterministic argmax(theta - lambda * normalized_cost)
    load and hash-check its unchanged instructions and required dependencies
    proposal := planner(binding, stage, observed state)

    if host preflight fails:
        return BLOCKED, NEED_INPUT, or NEED_APPROVAL
    decision := controller.issue(proposal, fresh state, available tools, approval)
    if decision != DISPATCH:
        return the persisted status              # never replay blindly

    execute through the existing host adapter using the action ID
    verifier := approved verifier for this exact proposal
    receipt := verifier.check(real external evidence)
    controller.resolve(authenticated receipt)
    continue from the resulting state, never from a narrated success claim
```

## 9. Validation scope and limitations

The included tests exercise the local routing equations, authorization binding, action identity, durable status, quotas, and receipt handling with synthetic fixtures. They do not benchmark model quality, test the user's live services, validate website selectors, or prove end-to-end security. The kernel is not a sandbox: a process that can read the signing key or rewrite the database can bypass this in-process reference. Put the controller and authority behind an actual privilege boundary in deployment. Raw action arguments are not exported in event records, but event identifiers and evidence references still require privacy review.

No edits were made to the supplied BOT Skills archive. The demo contract exists only in Python test fixtures and is not a new skill added to that collection.

## Design basis

The user-supplied BOT Skills documents motivate scoped authorization, exact-cart approval, stopping on ambiguous outcomes, stable helper continuity, and distinguishing successful process completion from verified task success. This formalization and kernel are new implementation work; they are not claimed to be contained in those documents.

External background (not performance evidence for this implementation):

- Agent Skills, integration guide: https://agentskills.io/client-implementation/adding-skills-support
- Agent Skills, file format: https://agentskills.io/specification
- Voyager, skill retrieval and accumulation in Minecraft: https://voyager.minedojo.org/
