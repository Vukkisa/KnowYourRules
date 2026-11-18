"""Stage 6D: ServeFilter edge cases without a server or an index: misconfiguration, errors while checking, mirror changes
without registry changes, index/registry reconciliation, readiness, mirror repair. Offline; fake embedder."""
import json
import os
import unittest

import test_document_lifecycle as tdl
from test_document_lifecycle import V1, V2

from backend import document_lifecycle as dl


class FilterTests(tdl.Base):
    def test_a_set_but_empty_environment_variable_is_a_misconfiguration_not_an_off_switch(self):
        f = dl.ServeFilter.from_env({"TG_LIFECYCLE_DIR": ""})
        self.assertTrue(f.enabled)
        self.assertFalse(f.servable("a" * 64))
        self.assertEqual(f.health()["state"], "missing")
        self.assertFalse(dl.ServeFilter.from_env({"TG_LIFECYCLE_DIR": "   "}).servable("a" * 64))
        self.assertFalse(dl.ServeFilter.from_env({}).enabled)
        self.assertTrue(dl.ServeFilter.from_env({}).servable("a" * 64))
        self.assertTrue(dl.ServeFilter.from_env({}).ready())

    def test_an_error_while_checking_never_turns_the_filter_off(self):
        e = self.approve_v1()
        f = dl.ServeFilter(self.state)
        self.assertTrue(f.servable(e.sha256))
        orig = dl.audit_problems
        dl.audit_problems = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            (self.state / "registry.json").write_text((self.state / "registry.json").read_text() + " ")   # force a re-read
            self.assertFalse(f.servable(e.sha256))
            self.assertEqual(f.digest(), "unreadable")
            self.assertEqual(f.health()["state"], "unreadable")
        finally:
            dl.audit_problems = orig
        for odd in (None, 5, ["x"], {"a": 1}, b"bytes"):
            self.assertFalse(f.servable(odd))

    def test_a_mirror_change_without_any_registry_change_is_noticed(self):
        e = self.approve_v1()
        f = dl.ServeFilter(self.state)
        self.assertTrue(f.servable(e.sha256))
        (self.state / "audit.jsonl").unlink()
        self.assertFalse(f.servable(e.sha256))
        self.assertEqual(f.health()["state"], "audit_failed")
        self.assertIn("missing", " ".join(f.health()["problems"]))

    def test_reconciliation_withholds_a_document_whose_chunk_count_disagrees(self):
        e = self.approve_v1()
        f = dl.ServeFilter(self.state)
        self.assertTrue(f.servable(e.sha256))                       # not reconciled yet: registry alone
        f.reconcile({e.sha256: 3})
        self.assertTrue(f.servable(e.sha256))
        self.assertTrue(f.ready())
        f.reconcile({e.sha256: 2})
        self.assertFalse(f.servable(e.sha256))
        self.assertEqual((f.health()["state"], f.health()["servable_documents"], f.ready()), ("index_mismatch", 0, False))
        f.reconcile({})
        self.assertFalse(f.servable(e.sha256))
        f.reconcile({e.sha256: 3, "z" * 64: 9})                      # extra documents in the index do not matter to the registry's own
        self.assertTrue(f.servable(e.sha256))

    def test_ready_needs_at_least_one_servable_document(self):
        f = dl.ServeFilter(self.state)
        e, _ = self.ingest(V1)
        self.assertEqual((f.health()["state"], f.ready()), ("ok", False))        # a registry with only a pending version
        self.lc.approve(e.id, 1, by="r")
        self.assertTrue(f.ready())
        self.lc.withdraw(e.id, 1, by="r")
        self.assertFalse(f.ready())

    def test_health_carries_no_document_text(self):
        e = self.approve_v1()
        text = json.dumps(dl.ServeFilter(self.state).health())
        self.assertNotIn("Riders shall wear", text)

    def test_the_audit_mirror_can_be_recreated_once_the_chain_verifies_and_never_overwritten(self):
        e = self.approve_v1()
        f = dl.ServeFilter(self.state)
        (self.state / "audit.jsonl").unlink()
        with self.assertRaises(dl.LifecycleError):
            self.lc.withdraw(e.id, 1, by="r")                                     # mutations refuse while the mirror is missing
        with self.assertRaises(dl.LifecycleError):
            self.lc.repair_audit_mirror("")                                       # named operator required
        out = self.lc.repair_audit_mirror("operator-1", "mirror lost in a disk cleanup")
        self.assertEqual(self.lc.audit_check(), [])
        self.assertTrue(f.servable(e.sha256))
        last = self.lc.load()["events"][-1]
        self.assertEqual((last["op"], last["by"]), ("audit_mirror_rebuilt", "operator-1"))
        self.assertIn("could not be cross-checked", last["caveat"])
        self.assertEqual(len((self.state / "audit.jsonl").read_text().splitlines()), out["events"])
        with self.assertRaises(dl.LifecycleError):
            self.lc.repair_audit_mirror("operator-1")                             # a mirror now exists: evidence, not overwritten

    def test_repair_refuses_when_the_registry_chain_itself_is_broken(self):
        e = self.approve_v1()
        reg = json.loads((self.state / "registry.json").read_text())
        reg["events"][0]["note"] = "forged"
        (self.state / "registry.json").write_text(json.dumps(reg))
        (self.state / "audit.jsonl").unlink()
        with self.assertRaises(dl.LifecycleError) as cm:
            self.lc.repair_audit_mirror("operator-1")
        self.assertIn("chain is broken", str(cm.exception))

    def test_a_lifecycle_operation_that_changes_the_index_leaves_the_running_filter_closed_for_the_new_version(self):
        e = self.approve_v1()
        f = dl.ServeFilter(self.state)
        f.reconcile({e.sha256: 3})                                  # what the running server saw at startup
        e2, _ = self.ingest(V2)
        self.lc.approve(e.id, 2, by="r")
        self.assertFalse(f.servable(e.sha256))                      # superseded
        self.assertFalse(f.servable(e2.sha256))                     # approved, but its chunks are not in the running index
        self.lc.rollback(e.id, 1, by="r")
        self.assertTrue(f.servable(e.sha256))                       # restored chunks match what the server loaded


if __name__ == "__main__":
    unittest.main()
