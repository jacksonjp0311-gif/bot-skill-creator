from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from bsc.control import (Action, Authority, Conflict, Controller, GateError, Outcome,
                       Reliability, Skill, ToolRule, digest, rank)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.now = 1000.0
        self.authority = Authority(b'x' * 32)
        self.skill = Skill("test", "1", digest("fixture"), "buy", ("place",))
        self.rules = {"place": ToolRule(True, 2)}
        self.path = Path(self.tmp.name) / "ledger.db"
        self.c = self.controller()
        self.c.start("r", "test-scope", max_actions=2, max_units=4)
        self.a = Action.create(run_id="r", step_id="s", skill=self.skill, tool="place",
            params={"total_minor":3420}, observed_state="state-1", verifier_id="v1")
        self.kw = dict(live_state="state-1", available_tools=frozenset({"place"}))
        self.approval = self.authority.approve(self.a, 1100.0)

    def controller(self):
        return Controller(self.path, skills=[self.skill], tool_rules=self.rules,
            authority=self.authority, verifier_ids=frozenset({"v1"}), clock=lambda:self.now)

    def tearDown(self):
        self.c.close()
        self.tmp.cleanup()

    def issue(self, a=None):
        a = a or self.a
        return self.c.issue(a, approval=self.authority.approve(a, 1100.0), **self.kw)

    def resolve(self, outcome=Outcome.SUCCESS):
        return self.c.resolve(self.authority.attest(self.a, outcome,
                            "fixture:receipt" if outcome != Outcome.UNKNOWN else ""))

    def test_approval_required(self):
        with self.assertRaisesRegex(GateError, "APPROVAL"):
            self.c.issue(self.a, **self.kw)
        self.assertEqual(self.c.statistics("test-scope", "buy"), {})

    def test_price_change_invalidates_approval(self):
        changed = replace(self.a, params_json='{"total_minor":4000}')
        with self.assertRaisesRegex(GateError, "APPROVAL"):
            self.c.issue(changed, approval=self.approval, **self.kw)

    def test_stale_observation_blocks(self):
        with self.assertRaisesRegex(GateError, "STATE_CHANGED"):
            self.c.issue(self.a, live_state="state-2", available_tools=frozenset({"place"}), approval=self.approval)

    def test_expired_approval(self):
        self.now=1100.0
        with self.assertRaisesRegex(GateError, "APPROVAL"):
            self.c.issue(self.a, approval=self.approval, **self.kw)

    def test_forged_approval(self):
        with self.assertRaisesRegex(GateError, "APPROVAL"):
            self.c.issue(self.a, approval=replace(self.approval, signature="bad"), **self.kw)

    def test_unavailable_tool(self):
        with self.assertRaisesRegex(GateError, "TOOL"):
            self.c.issue(self.a, live_state="state-1", available_tools=frozenset(), approval=self.approval)

    def test_unapproved_skill(self):
        with self.assertRaisesRegex(GateError, "UNAPPROVED_SKILL"):
            self.issue(replace(self.a, skill_key="unknown"))

    def test_unapproved_verifier(self):
        with self.assertRaisesRegex(GateError, "UNAPPROVED_VERIFIER"):
            self.issue(replace(self.a, verifier_id="self-grade"))

    def test_duplicate_dispatch_and_receipt(self):
        self.assertEqual(self.issue(), "DISPATCH")
        self.assertEqual(self.issue(), "IN_FLIGHT")
        self.assertTrue(self.resolve())
        self.assertFalse(self.resolve())
        self.assertEqual(self.issue(), "SUCCESS")
        self.assertEqual(self.c.statistics("test-scope", "buy")[self.skill.key].success, 1)

    def test_changed_same_step_is_conflict(self):
        self.issue()
        with self.assertRaises(Conflict):
            self.issue(replace(self.a, params_json='{"total_minor":9999}'))

    def test_pending_not_counted(self):
        self.issue()
        self.assertEqual(self.c.statistics("test-scope", "buy"), {})

    def test_other_step_waits_for_receipt(self):
        self.issue()
        with self.assertRaisesRegex(GateError, "WAITING"):
            self.issue(replace(self.a, step_id="next"))

    def test_receipt_cannot_be_forged(self):
        self.issue()
        receipt=self.authority.attest(self.a, Outcome.SUCCESS, "fixture:receipt")
        with self.assertRaisesRegex(GateError, "UNAUTHENTICATED"):
            self.c.resolve(replace(receipt, signature="bad"))

    def test_receipt_is_action_bound(self):
        self.issue()
        changed=replace(self.a, params_json='{"total_minor":9999}')
        with self.assertRaises(Conflict):
            self.c.resolve(self.authority.attest(changed, Outcome.SUCCESS, "fixture:receipt"))

    def test_terminal_conflict(self):
        self.issue(); self.resolve()
        with self.assertRaises(Conflict):
            self.resolve(Outcome.FAILURE)

    def test_unknown_halts_run(self):
        self.issue(); self.resolve(Outcome.UNKNOWN)
        with self.assertRaisesRegex(GateError, "RUN_HALTED"):
            self.issue(replace(self.a, step_id="retry"))
        stats=self.c.statistics("test-scope", "buy")[self.skill.key]
        self.assertEqual(stats, Reliability(0,0,1))
        self.assertEqual(stats.conditional_success, 0.5)

    def test_scope_isolated(self):
        self.issue(); self.resolve()
        self.assertEqual(self.c.statistics("other-environment", "buy"), {})
        self.assertEqual(self.c.statistics("test-scope", "other-objective"), {})

    def test_restart_does_not_redispatch(self):
        self.issue(); self.c.close(); self.c=self.controller()
        self.assertEqual(self.issue(), "IN_FLIGHT")

    def test_second_controller_does_not_redispatch(self):
        second=self.controller()
        try:
            self.assertEqual(self.issue(), "DISPATCH")
            self.assertEqual(second.issue(self.a, approval=self.approval, **self.kw), "IN_FLIGHT")
        finally:
            second.close()

    def test_run_deadline(self):
        self.now=1400.0
        with self.assertRaisesRegex(GateError, "DEADLINE"):
            self.issue()

    def test_budget(self):
        self.issue(); self.resolve()
        b=replace(self.a, step_id="s2")
        self.issue(b)
        self.c.resolve(self.authority.attest(b, Outcome.SUCCESS, "fixture:receipt2"))
        with self.assertRaisesRegex(GateError, "BUDGET"):
            self.issue(replace(self.a, step_id="s3"))

    def test_policy_change_blocks_existing_run(self):
        self.c.close(); self.rules={"place":ToolRule(True,3)}; self.c=self.controller()
        with self.assertRaisesRegex(GateError, "POLICY_CHANGED"):
            self.issue()

    def test_evidence_required(self):
        with self.assertRaises(ValueError):
            self.authority.attest(self.a, Outcome.SUCCESS)

    def test_export_does_not_store_action_params(self):
        self.issue(); self.resolve()
        p=Path(self.tmp.name)/"events.jsonl"
        self.c.export_events(p)
        self.assertNotIn("total_minor",p.read_text())
        self.assertIn("RESOLVE",p.read_text())


class RoutingTests(unittest.TestCase):
    def test_exact_rate_identity(self):
        for s,f,u in [(0,0,0),(10,2,0),(2,5,7),(0,0,100)]:
            r=Reliability(s,f,u)
            self.assertAlmostEqual(r.verified_success,r.resolution*r.conditional_success)

    def test_unknown_is_not_verified_failure(self):
        a,b=Reliability(7,2,0),Reliability(7,2,5)
        self.assertEqual(a.conditional_success,b.conditional_success)
        self.assertLess(b.verified_success,a.verified_success)

    def test_rank_and_filter(self):
        a=Skill("a","1",digest("a"),"lookup",("read",))
        b=Skill("b","1",digest("b"),"lookup",("read",))
        other=Skill("other","1",digest("o"),"buy",("write",))
        ranked=rank([a,b,other],objective="lookup",approved_keys=frozenset({a.key,b.key,other.key}),
            available_tools=frozenset({"read"}),history={a.key:Reliability(8,1,1),b.key:Reliability(4,4,2)},
            normalized_cost={a.key:0.2,b.key:0.1})
        self.assertEqual([s.name for _,s in ranked],["a","b"])

    def test_no_eligible_means_no_fabricated_selection(self):
        a=Skill("a","1",digest("a"),"lookup",("read",))
        self.assertEqual(rank([a],objective="lookup",approved_keys=frozenset(),
            available_tools=frozenset({"read"}),history={},normalized_cost={}),[])

    def test_source_unchanged_and_hash_check(self):
        with TemporaryDirectory() as d:
            p=Path(d)/"SKILL.md"; original=b"---\r\nname: sample\r\n---\r\n"
            p.write_bytes(original)
            s=Skill.from_file(p,name="sample",version="1",objective="lookup",tools=("read",))
            self.assertEqual(s.load_unchanged(p), original)
            self.assertEqual(p.read_bytes(),original)
            p.write_bytes(b"changed")
            with self.assertRaises(GateError):
                s.load_unchanged(p)

    def test_missing_cost_is_not_assumed_free(self):
        a=Skill("a","1",digest("a"),"lookup",("read",))
        with self.assertRaisesRegex(ValueError, "Missing declared cost"):
            rank([a],objective="lookup",approved_keys=frozenset({a.key}),
                 available_tools=frozenset({"read"}),history={},normalized_cost={})

    def test_counts_must_be_nonnegative_integers(self):
        with self.assertRaises(ValueError):
            Reliability(-1,0,0)
        with self.assertRaises(ValueError):
            Reliability(1.5,0,0)

    def test_version_contract_isolation(self):
        a=Skill("a","1",digest("same-source"),"lookup",("read",))
        self.assertNotEqual(a.key,replace(a,version="2").key)
        self.assertNotEqual(a.key,replace(a,tools=("write",)).key)


if __name__ == "__main__":
    unittest.main()
