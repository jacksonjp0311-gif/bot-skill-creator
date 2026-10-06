# Mathematics · the reasoning beneath the recipe

Bot Skill Creator v0.1 uses the BOT Agent Algorithm v0.1 as a control template.
The original specification is preserved in `docs/provenance/` in the creator repository.
This file separates inherited mathematics, implemented artifact controls, and proposed
host behavior. No equation below establishes novel science or measured performance superiority.

## 1. What the algorithm estimates

Fix a skill-step binding, its version, its objective, and its context scope. A binding is
an alternative way to achieve the SAME next objective, not any vaguely relevant skill.
Count terminal attempts as S (verified success), F (verified failure), or U (unknown).
Active attempts and proposals blocked before issue do not enter these counts.

Assume, within that scope, outcomes have categorical probabilities
p = (p_S, p_F, p_U), with the declared prior:

$$p \sim \operatorname{Dirichlet}(1,1,1).$$

This is an exchangeability/stationarity modeling assumption, not a fact about changing websites.
After the counts, let a=S+1, b=F+1, c=U+1, and A=a+b+c.

$$p\mid D \sim \operatorname{Dirichlet}(a,b,c).$$

The posterior predictive probability of VERIFIED SUCCESS is:

$$\hat\theta = \mathbb E[p_S\mid D]=\frac{S+1}{S+F+U+3}.$$

Its posterior variance under this model is:

$$\operatorname{Var}(p_S\mid D)=\frac{a(A-a)}{A^2(A+1)}.$$

The mean is implemented. Credible intervals, calibration and drift detection are NOT
implemented in this release. A prior mean is not a measured accuracy or confidence guarantee.

## 2. Separate observability from conditional quality

Define Q=p_S+p_F, the probability of a verifiable terminal outcome, and
M=p_S/(p_S+p_F), the success probability conditional on verification.
Dirichlet aggregation gives Q ~ Beta(a+b,c) and M ~ Beta(a,b); these two
transformed variables are independent under this particular posterior.
Thus both the product identity and the product of means agree:

$$\hat q=\frac{S+F+2}{S+F+U+3},\qquad
\hat\mu=\frac{S+1}{S+F+2},$$

$$\boxed{\hat q\hat\mu=\hat\theta=\frac{S+1}{S+F+U+3}}.$$

An unknown result increases U: it lowers q, but does not change mu. It is not
recorded as a verified bad result. An active attempt is not a terminal unknown.
With no observations, q=2/3, mu=1/2, theta=1/3 by construction.

This identity should not be generalized to arbitrary correlated estimators:
E[XY] is not generally E[X]E[Y]. Here it follows from the declared coherent model.

## 3. Eligibility is a set, not a soft penalty

For observed context x and objective g, construct:

$$\mathcal F(x,g)=\{s:\operatorname{reviewed}(s)\land
\operatorname{objective}(s)=g\land\operatorname{inputs}(s,x)\land
\operatorname{capabilities}(s,x)\land\operatorname{dependencies}(s)\land
\operatorname{contextFits}(s,x)\}.$$

For eligible alternatives with normalized declared costs c_s in [0,1]:

$$s^*=\arg\max_{s\in\mathcal F(x,g)}[\hat\theta_s-\lambda c_s],\quad\lambda\geq0.$$

The 0.15 weight in the interactive calculator is illustrative. Costs must share a
specified scale. A 0.2 cost is not $0.20. Ties are resolved by stable binding key.
No exploration bonus is implemented. Greedy selection can starve untried routes;
use separate authorized trials and held-out evaluation, not hidden live exploration.
Historical selection bias and a changed model/runtime invalidate naive comparisons.
Permission is checked at the action boundary. Even a score of 1 cannot authorize an action.

## 4. Exact-action authorization and local at-most-once issue

An action freezes the run ID, stable logical step, binding/version, objective, tool,
canonical arguments, relevant observed-state fingerprint, and verifier ID.

$$\operatorname{ID}(a)=H(\operatorname{runID},\operatorname{stepID}),$$
$$\operatorname{fingerprint}(a)=H(\operatorname{frozenProposal}(a)).$$

The host approval authenticates that exact fingerprint and has an expiry. Changed
arguments under the same logical step conflict; a new approval is not inferred.
A transaction persists ISSUE and reserves quota before returning DISPATCH.
The controller never returns a second DISPATCH for that logical ID in its database.

This does NOT guarantee exactly-once remote execution. A crash can happen between
ISSUE and the external request or between execution and receipt. Reconcile rather
than replay. Provider idempotency and conditional requests remain adapter responsibilities.
Hashing state does not eliminate the time-of-check/time-of-use race.

A signed receipt authenticates a host statement; it does not prove external truth.
The host verifier must check the actual task postcondition against real evidence.

## 5. How the creator uses this algorithm

The creator compiles a proposal into a deterministic candidate artifact set.
The browser previews that exact set and shows its fingerprint. Export approval is
bound to project ID, revision and file hashes. The local host passes the export
through the reference Controller, writes the ZIP, re-reads it, and attests only
that the artifact round trip succeeded. It does not attest that the generated skill works live.

The exported workflow contains the seven stages and the required host boundaries.
A SKILL.md paragraph is NOT a privilege boundary. Imported operations are contracts,
not installed tools. The future harness must provide source validation, resource ACLs,
credential custody, timeout/cost metering, actual execution and evidence verification.

CLI compilation is an explicitly requested local file-writing operation. The CLI does
not invent an interactive approval UI and does not run the imported APIs. Its JSON
bridge is an authoring protocol, not an execution protocol or an MCP server.

## 6. Hard guarantees versus assumptions

The tested reference kernel covers local state transitions, exact-action approvals,
identity conflicts, quota reservation, signed-receipt validation, duplicate suppression,
and terminal UNKNOWN halting. These hold only within its declared trusted-host model.
A worker able to read the signing key, replace the controller or edit the database can
bypass it. Deploy behind a real privilege boundary where enforcement is required.

Static package checks cover structure and digest consistency. An attacker who replaces
both an artifact and its manifest can create a consistent new set. An external trusted
release digest or signature is required for authenticity. Neither internal digests nor
passing unit tests prove universal safety, truth, correct permissions, or model quality.

## 7. Learning: specified, not self-promoted

Terminal evidence may update future-run ranking statistics within an approved policy.
Freeze the history map during a run. Keep scopes versioned. Behavioral edits follow:

observation → candidate → representative tests → held-out comparison → review → activation.

No candidate may modify permissions, approve itself, replace the verifier or overwrite
preserved skill originals. The creator does not implement autonomous promotion or train
model weights. Treat this as a testable software design, not a claim of superintelligence.

## Sources and lineage

- BOT Agent Algorithm v0.1, supplied in this conversation; preserved unmodified in the creator repository.
- Agent Skills format: https://agentskills.io/specification
- OpenAPI 3.1.1 specification: https://spec.openapis.org/oas/v3.1.1.html
- These are format/protocol references, not performance evidence for this implementation.
