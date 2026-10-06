"""BOT Agent Algorithm v0.1: an offline-tested, host-mediated control kernel.

Model-visible operations should be limited to proposals and read-only status.
Authority methods and controller construction belong to the trusted host.
No network clients, browser automation, or automatic skill rewriting are included.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from hashlib import sha256
import hmac
import json
import math
from pathlib import Path
import sqlite3
import time
from typing import Callable, Iterable, Mapping


def canonical(value: object) -> str:
    """Canonical encoding for this Python implementation, not a cross-language spec."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def digest(value: object) -> str:
    return sha256(canonical(value).encode("utf-8")).hexdigest()


class GateError(RuntimeError):
    """A host prerequisite is absent; do not dispatch."""


class Conflict(RuntimeError):
    """A supposedly identical action or receipt changed; stop and reconcile."""


class Outcome(str, Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Skill:
    name: str
    version: str
    source_hash: str
    objective: str
    tools: tuple[str, ...]

    @property
    def key(self) -> str:
        # Include the reviewed adapter contract as well as the source file hash.
        return self.name + "@" + self.version + ":" + digest(asdict(self))

    @classmethod
    def from_file(cls, path: Path, *, name: str, version: str,
                  objective: str, tools: tuple[str, ...]) -> "Skill":
        """Read-only import. Host supplies reviewed metadata; no YAML repair."""
        return cls(name, version, sha256(path.read_bytes()).hexdigest(), objective, tools)

    def load_unchanged(self, path: Path) -> bytes:
        data = path.read_bytes()
        if sha256(data).hexdigest() != self.source_hash:
            raise GateError("SOURCE_CHANGED")
        return data


@dataclass(frozen=True)
class ToolRule:
    requires_approval: bool
    quota_units: int = 1

    def __post_init__(self) -> None:
        if type(self.quota_units) is not int or self.quota_units < 1:
            raise ValueError("quota_units must be a positive integer")


@dataclass(frozen=True)
class Action:
    run_id: str
    step_id: str
    skill_key: str
    objective: str
    tool: str
    params_json: str
    observed_state: str
    verifier_id: str

    @classmethod
    def create(cls, *, run_id: str, step_id: str, skill: Skill, tool: str,
               params: Mapping[str, object], observed_state: str,
               verifier_id: str) -> "Action":
        return cls(run_id, step_id, skill.key, skill.objective, tool,
                   canonical(dict(params)), observed_state, verifier_id)

    @property
    def action_id(self) -> str:
        # Stable logical step identity: changing arguments must not create a retry.
        return digest([self.run_id, self.step_id])

    @property
    def fingerprint(self) -> str:
        return digest(asdict(self))

    @property
    def params(self) -> dict:
        return json.loads(self.params_json)


@dataclass(frozen=True)
class Approval:
    fingerprint: str
    expires_at: float
    signature: str


@dataclass(frozen=True)
class Receipt:
    action_id: str
    fingerprint: str
    outcome: Outcome
    evidence_ref: str
    signature: str


class Authority:
    """Trusted host only. Keep this object/key outside the agent's tool surface.

    The host must actually obtain permission before approving and actually check
    external evidence before attesting. A signature authenticates the host's
    statement; it does not establish that the statement is true.
    """
    def __init__(self, secret: bytes):
        if len(secret) < 32:
            raise ValueError("Use at least 32 secret bytes")
        self.__secret = secret

    def _sign(self, value: object) -> str:
        return hmac.new(self.__secret, canonical(value).encode("utf-8"), "sha256").hexdigest()

    def approve(self, action: Action, expires_at: float) -> Approval:
        if not math.isfinite(expires_at):
            raise ValueError("Expiry must be finite")
        body = ["approval", action.fingerprint, expires_at]
        return Approval(action.fingerprint, expires_at, self._sign(body))

    def valid_approval(self, approval: Approval, action: Action, now: float) -> bool:
        return (math.isfinite(approval.expires_at)
                and now < approval.expires_at
                and approval.fingerprint == action.fingerprint
                and hmac.compare_digest(approval.signature,
                    self._sign(["approval", approval.fingerprint, approval.expires_at])))

    def attest(self, action: Action, outcome: Outcome, evidence_ref: str = "") -> Receipt:
        outcome = Outcome(outcome)
        if outcome != Outcome.UNKNOWN and not evidence_ref:
            raise ValueError("A verified outcome needs an evidence reference")
        body = ["receipt", action.action_id, action.fingerprint, outcome.value, evidence_ref]
        return Receipt(action.action_id, action.fingerprint, outcome, evidence_ref, self._sign(body))

    def valid_receipt(self, receipt: Receipt) -> bool:
        body = ["receipt", receipt.action_id, receipt.fingerprint,
                receipt.outcome.value, receipt.evidence_ref]
        return hmac.compare_digest(receipt.signature, self._sign(body))


@dataclass(frozen=True)
class Reliability:
    success: int = 0
    failure: int = 0
    unknown: int = 0

    def __post_init__(self) -> None:
        if any(type(n) is not int or n < 0 for n in (self.success, self.failure, self.unknown)):
            raise ValueError("Outcome counts must be nonnegative integers")

    @property
    def resolution(self) -> float:
        return (self.success + self.failure + 2) / (self.success + self.failure + self.unknown + 3)

    @property
    def conditional_success(self) -> float:
        return (self.success + 1) / (self.success + self.failure + 2)

    @property
    def verified_success(self) -> float:
        return (self.success + 1) / (self.success + self.failure + self.unknown + 3)


def rank(skills: Iterable[Skill], *, objective: str,
         approved_keys: frozenset[str], available_tools: frozenset[str],
         history: Mapping[str, Reliability], normalized_cost: Mapping[str, float],
         cost_weight: float = 0.15) -> list[tuple[float, Skill]]:
    """Rank reviewed alternatives for the SAME objective. This is not authorization.

    Cost inputs are declared estimates in [0, 1], not measured dollar guarantees.
    Cold start uses an explicit symmetric three-outcome Dirichlet(1,1,1) prior.
    No live exploration bonus; ties are deterministic.
    """
    if not math.isfinite(cost_weight) or cost_weight < 0:
        raise ValueError("cost_weight must be finite and nonnegative")
    result = []
    for skill in skills:
        if skill.objective != objective or skill.key not in approved_keys:
            continue
        if not set(skill.tools).issubset(available_tools):
            continue
        if skill.key not in normalized_cost:
            raise ValueError("Missing declared cost estimate for " + skill.name)
        cost = normalized_cost[skill.key]
        if not math.isfinite(cost) or not 0 <= cost <= 1:
            raise ValueError("normalized cost must be in [0, 1]")
        stats = history.get(skill.key, Reliability())
        if min(stats.success, stats.failure, stats.unknown) < 0:
            raise ValueError("negative outcome counts")
        score = stats.verified_success - cost_weight * cost
        result.append((score, skill))
    return sorted(result, key=lambda pair: (-pair[0], pair[1].key))


class Controller:
    """Durable issue/resolve kernel; trusted host owns this API.

    Returns DISPATCH exactly once per logical action_id in this database, then
    IN_FLIGHT or its terminal outcome. This is a LOCAL at-most-once dispatch
    decision, not an exactly-once guarantee for an external service.
    """
    def __init__(self, database: str | Path, *, skills: Iterable[Skill],
                 tool_rules: Mapping[str, ToolRule], authority: Authority,
                 verifier_ids: frozenset[str], clock: Callable[[], float] = time.time):
        self.skills = {s.key: s for s in skills}
        self.rules = dict(tool_rules)
        self.authority = authority
        self.verifiers = verifier_ids
        self.clock = clock
        self.policy_id = digest({"skills": sorted(self.skills),
            "tools": {k: asdict(v) for k, v in self.rules.items()},
            "verifiers": sorted(verifier_ids)})
        self.db = sqlite3.connect(str(database), timeout=5, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY, scope TEXT NOT NULL, policy_id TEXT NOT NULL,
            max_actions INTEGER NOT NULL, max_units INTEGER NOT NULL,
            deadline REAL NOT NULL, halted INTEGER NOT NULL DEFAULT 0);
          CREATE TABLE IF NOT EXISTS attempts (
            id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
            skill_key TEXT NOT NULL, objective TEXT NOT NULL,
            fingerprint TEXT NOT NULL, units INTEGER NOT NULL,
            status TEXT NOT NULL, evidence_ref TEXT NOT NULL DEFAULT '');
          CREATE TABLE IF NOT EXISTS events (
            seq INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
            run_id TEXT NOT NULL, action_id TEXT, data TEXT NOT NULL);
        ''')

    def close(self) -> None:
        self.db.close()

    def _event(self, kind: str, run: str, action: str | None, data: object) -> None:
        self.db.execute("INSERT INTO events(kind,run_id,action_id,data) VALUES (?,?,?,?)",
                        (kind, run, action, canonical(data)))

    def start(self, run_id: str, scope: str, *, max_actions: int = 8,
              max_units: int = 16, ttl_seconds: float = 300) -> None:
        if (type(max_actions) is not int or max_actions < 1
                or type(max_units) is not int or max_units < 1
                or not math.isfinite(ttl_seconds) or ttl_seconds <= 0):
            raise ValueError("Run budgets must be positive and finite")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,0)",
                (run_id, scope, self.policy_id, max_actions, max_units, self.clock() + ttl_seconds))
            self._event("START", run_id, None, {"scope": scope, "policy_id": self.policy_id})
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def issue(self, action: Action, *, live_state: str,
              available_tools: frozenset[str], approval: Approval | None = None) -> str:
        """Call only AFTER host checks current inputs, ACLs, dependency hashes,
        and resource scope. live_state is a fresh relevant-state digest from the
        host, not an agent assertion. Do not dispatch unless return == DISPATCH.
        """
        self.db.execute("BEGIN IMMEDIATE")
        try:
            previous = self.db.execute("SELECT * FROM attempts WHERE id=?", (action.action_id,)).fetchone()
            if previous:
                if previous["fingerprint"] != action.fingerprint:
                    raise Conflict("ACTION_CHANGED: same step, different arguments/state/version")
                self.db.execute("COMMIT")
                return previous["status"]
            run = self.db.execute("SELECT * FROM runs WHERE id=?", (action.run_id,)).fetchone()
            if not run:
                raise GateError("UNKNOWN_RUN")
            if run["policy_id"] != self.policy_id:
                raise GateError("POLICY_CHANGED")
            if run["halted"]:
                raise GateError("RUN_HALTED: reconcile unknown outcome outside this run")
            if self.clock() >= run["deadline"]:
                raise GateError("DEADLINE_EXCEEDED")
            skill = self.skills.get(action.skill_key)
            if not skill or skill.objective != action.objective:
                raise GateError("UNAPPROVED_SKILL_OR_OBJECTIVE")
            rule = self.rules.get(action.tool)
            if not rule or action.tool not in skill.tools or action.tool not in available_tools:
                raise GateError("TOOL_UNAVAILABLE_OR_NOT_ALLOWED")
            if action.verifier_id not in self.verifiers:
                raise GateError("UNAPPROVED_VERIFIER")
            if action.observed_state != live_state:
                raise GateError("STATE_CHANGED: observe and prepare a new approval")
            if self.db.execute("SELECT 1 FROM attempts WHERE run_id=? AND status='IN_FLIGHT'",
                               (action.run_id,)).fetchone():
                raise GateError("WAITING_FOR_RECEIPT")
            used = self.db.execute("SELECT COUNT(*) AS n, COALESCE(SUM(units),0) AS u FROM attempts WHERE run_id=?",
                                   (action.run_id,)).fetchone()
            if used["n"] >= run["max_actions"] or used["u"] + rule.quota_units > run["max_units"]:
                raise GateError("BUDGET_EXCEEDED")
            if rule.requires_approval and (approval is None or not self.authority.valid_approval(approval, action, self.clock())):
                raise GateError("APPROVAL_REQUIRED_OR_INVALID")
            self.db.execute("INSERT INTO attempts VALUES (?,?,?,?,?,?,?,?)",
                (action.action_id, action.run_id, action.skill_key, action.objective,
                 action.fingerprint, rule.quota_units, "IN_FLIGHT", ""))
            self._event("ISSUE", action.run_id, action.action_id,
                        {"fingerprint": action.fingerprint, "units": rule.quota_units})
            self.db.execute("COMMIT")
            return "DISPATCH"
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise

    def resolve(self, receipt: Receipt) -> bool:
        """Only authenticated host evidence produces a terminal result.

        Identical duplicate = False/no-op. Conflicting result = stop/error.
        UNKNOWN halts the run, remains terminal, and is never auto-retried.
        """
        if not self.authority.valid_receipt(receipt):
            raise GateError("UNAUTHENTICATED_RECEIPT")
        if receipt.outcome != Outcome.UNKNOWN and not receipt.evidence_ref:
            raise GateError("MISSING_EVIDENCE")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("SELECT * FROM attempts WHERE id=?", (receipt.action_id,)).fetchone()
            if not row or row["fingerprint"] != receipt.fingerprint:
                raise Conflict("RECEIPT_DOES_NOT_MATCH_ISSUED_ACTION")
            if row["status"] != "IN_FLIGHT":
                if row["status"] == receipt.outcome.value and row["evidence_ref"] == receipt.evidence_ref:
                    self.db.execute("COMMIT")
                    return False
                raise Conflict("TERMINAL_RESULT_CONFLICT")
            self.db.execute("UPDATE attempts SET status=?,evidence_ref=? WHERE id=?",
                            (receipt.outcome.value, receipt.evidence_ref, receipt.action_id))
            self._event("RESOLVE", row["run_id"], receipt.action_id,
                        {"outcome": receipt.outcome.value, "evidence_ref": receipt.evidence_ref})
            if receipt.outcome == Outcome.UNKNOWN:
                self.db.execute("UPDATE runs SET halted=1 WHERE id=?", (row["run_id"],))
            self.db.execute("COMMIT")
            return True
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise

    def statistics(self, scope: str, objective: str) -> dict[str, Reliability]:
        """Project terminal receipts, never process exit codes or pending attempts."""
        rows = self.db.execute('''SELECT a.skill_key,a.status,COUNT(*) AS n
          FROM attempts a JOIN runs r ON r.id=a.run_id
          WHERE r.scope=? AND a.objective=? AND a.status!='IN_FLIGHT'
          GROUP BY a.skill_key,a.status''', (scope, objective))
        grouped: dict[str, dict[str, int]] = {}
        for row in rows:
            grouped.setdefault(row["skill_key"], {})[row["status"].lower()] = row["n"]
        return {k: Reliability(**v) for k, v in grouped.items()}

    def export_events(self, path: Path) -> None:
        """Explicit local export. Never pass raw secrets as identifiers/evidence refs."""
        with path.open("w", encoding="utf-8", newline="\n") as out:
            for row in self.db.execute("SELECT * FROM events ORDER BY seq"):
                event = dict(row)
                event["data"] = json.loads(event["data"])
                out.write(canonical(event) + "\n")
