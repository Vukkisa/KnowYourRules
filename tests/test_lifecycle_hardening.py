"""Stage 6C: cross-process locking, operator identity, audit integrity, warning-metadata integration. Real OS processes for
the locking tests (subprocess + tests/lifecycle_worker.py). Offline; fake embedder; temporary Chroma directories."""
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path

import test_document_lifecycle as tdl
from test_document_lifecycle import V1, V2
import test_lifecycle_bootstrap as tlb

from backend import document_lifecycle as dl

ROOT = Path(__file__).resolve().parent.parent
WORKER = ROOT / "tests" / "lifecycle_worker.py"


class Procs(tdl.Base):
    def spec(self, op, **kw):
        return dict(op=op, state=str(self.state), db=str(self.db), corpus=str(self.corpus), **kw)

    def start(self, op, **kw):
        p = subprocess.Popen([sys.executable, str(WORKER), json.dumps(self.spec(op, **kw))], cwd=ROOT,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: p.poll() is None and (p.kill(), p.wait()))
        return p

    @staticmethod
    def result(p, timeout=120):
        out, err = p.communicate(timeout=timeout)
        lines = [x for x in out.splitlines() if x.startswith("{")]
        if not lines:
            raise AssertionError(f"worker produced no result\nstdout={out}\nstderr={err[-1500:]}")
        return json.loads(lines[-1])

    @staticmethod
    def wait_for(p, word, timeout=60):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            line = p.stdout.readline()
            if word in line:
                return
            if not line and p.poll() is not None:
                break
        raise AssertionError(f"worker never printed {word}: {p.stderr.read()[-1500:] if p.poll() is not None else ''}")

    def write(self, name, text):
        (self.corpus / name).write_text(text)

    def lock(self, timeout=0.3):
        return dl.Lifecycle(self.state, self.db, embeddings=self.emb, chunker=tdl.fake_chunker, lock_timeout=timeout,
                            invalidate=lambda *a: None)


class ConcurrencyTests(Procs):
    def test_parallel_ingest_and_approve_of_different_sources_loses_nothing(self):
        n = 4
        for i in range(n):
            self.write(f"d{i}.txt", f"Rule {i + 1}. Document number {i} rule text.\nRule {i + 50}. More text for {i}.")
        procs = [self.start("ingest_approve", source=f"src-{i}", file=f"d{i}.txt", by=f"w{i}") for i in range(n)]
        results = [self.result(p) for p in procs]
        self.assertTrue(all(r["ok"] for r in results), results)
        lc = self.make()
        reg = lc.load()
        self.assertEqual(sorted(reg["sources"]), [f"src-{i}" for i in range(n)])
        self.assertTrue(all(s["active_version"] == 1 for s in reg["sources"].values()))
        self.assertEqual(len(self.hashes()), n)
        self.assertEqual(lc.verify(), [])
        self.assertEqual(lc.audit_check(), [])
        self.assertEqual([e["seq"] for e in reg["events"]], list(range(len(reg["events"]))))
        self.assertEqual(len(reg["events"]), 2 * n)                      # one ingest + one approve each, none lost
        self.assertEqual(len(self.state.joinpath("audit.jsonl").read_text().splitlines()), 2 * n)

    def test_two_processes_approving_the_same_pending_version_cannot_both_succeed(self):
        e, _ = self.ingest(V1)
        a, b = self.start("approve", source=e.id, version=1, by="p1"), self.start("approve", source=e.id, version=1, by="p2")
        ra, rb = self.result(a), self.result(b)
        self.assertEqual(sorted([ra["ok"], rb["ok"]]), [False, True], (ra, rb))
        failed = ra if not ra["ok"] else rb
        self.assertIn("only a pending version can be approved", failed["error"])
        reg = self.make().load()
        self.assertEqual([h["state"] for h in reg["sources"][e.id]["versions"]["1"]["history"]], ["pending", "approved"])
        self.assertEqual(len([ev for ev in reg["events"] if ev["op"] == "approve"]), 1)
        self.assertEqual(len(self.hashes()), 1)

    def test_two_versions_of_one_source_approved_at_once_end_with_exactly_one_active(self):
        e, _ = self.ingest(V1)
        self.ingest(V2)
        a, b = self.start("approve", source=e.id, version=1, by="p1"), self.start("approve", source=e.id, version=2, by="p2")
        results = [self.result(a), self.result(b)]
        self.assertTrue(all(r["ok"] for r in results), results)
        lc = self.make()
        reg = lc.load()["sources"][e.id]
        states = sorted(v["state"] for v in reg["versions"].values())
        self.assertEqual(states, ["approved", "superseded"])
        self.assertEqual(self.hashes(), {reg["versions"][str(reg["active_version"])]["sha256"]})
        self.assertEqual(lc.verify(), [])
        self.assertEqual(lc.audit_check(), [])

    def test_a_second_process_gets_a_clear_timeout_while_the_lock_is_held(self):
        e = self.approve_v1()
        holder = self.start("hold_lock", by="holder-op", hold=4)
        self.wait_for(holder, "LOCKED")
        before = (self.state / "registry.json").read_bytes()
        lc = self.lock(timeout=0.3)
        t0 = time.monotonic()
        with self.assertRaises(dl.LockTimeout) as cm:
            lc.withdraw(e.id, 1, by="impatient")
        self.assertLess(time.monotonic() - t0, 3)
        msg = str(cm.exception)
        self.assertIn("hold_lock", msg)
        self.assertIn("holder-op", msg)
        self.assertIn("Nothing was changed", msg)
        self.assertEqual((self.state / "registry.json").read_bytes(), before)
        self.assertTrue(self.result(holder)["ok"])
        lc.withdraw(e.id, 1, by="patient")                               # lock free again

    def test_a_waiting_process_proceeds_when_the_holder_releases(self):
        e = self.approve_v1()
        holder = self.start("hold_lock", by="holder", hold=1.5)
        self.wait_for(holder, "LOCKED")
        waiter = self.start("withdraw", source=e.id, version=1, by="waiter", timeout=20)
        self.assertTrue(self.result(holder)["ok"])
        self.assertTrue(self.result(waiter)["ok"])
        self.assertEqual(self.make().status()[e.id]["versions"]["1"], "withdrawn")

    def test_a_killed_lock_holder_does_not_block_anyone(self):
        e = self.approve_v1()
        holder = self.start("hold_lock", by="doomed", hold=120)
        self.wait_for(holder, "LOCKED")
        holder.send_signal(signal.SIGKILL)
        holder.wait()
        self.assertTrue((self.state / ".lifecycle.lock").exists())      # the file stays; the OS lock is gone
        self.lock(timeout=2).withdraw(e.id, 1, by="after-kill")
        self.assertEqual(self.make().status()[e.id]["versions"]["1"], "withdrawn")

    def test_leftover_garbage_in_the_lock_file_blocks_nothing(self):
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / ".lifecycle.lock").write_text("pid 999999 held forever\x00\xff")
        e, _ = self.ingest(V1)
        self.lock(timeout=1).approve(e.id, 1, by="op")

    def test_a_process_killed_mid_swap_leaves_the_old_index_and_recovers(self):
        e = self.approve_v1()
        self.ingest(V2)
        before = sorted(self.live())
        p = self.start("slow_swap", source=e.id, version=2, by="victim", hold=60)
        self.wait_for(p, "IN_SWAP")
        p.send_signal(signal.SIGKILL)
        p.wait()
        lc = self.lock(timeout=2)
        with self.assertRaises(dl.LifecycleError) as cm:
            lc.withdraw(e.id, 1, by="op")
        self.assertIn("interrupted", str(cm.exception))
        self.assertFalse(dl.ServeFilter(self.state).servable(e.sha256))   # fail closed until recovered
        self.assertEqual(lc.recover("operator")["action"], "aborted")
        self.assertEqual(sorted(self.live()), before)
        self.assertEqual(lc.verify(), [])
        self.assertTrue(dl.ServeFilter(self.state).servable(e.sha256))
        lc.approve(e.id, 2, by="op")                                     # and the operation can simply be retried

    def test_read_only_operations_never_wait_for_the_lock(self):
        e = self.approve_v1()
        holder = self.start("hold_lock", by="holder", hold=5)
        self.wait_for(holder, "LOCKED")
        lc = self.lock(timeout=0.2)
        t0 = time.monotonic()
        lc.status()
        lc.verify()
        lc.audit_check()
        lc.warning_coverage()
        self.assertTrue(dl.ServeFilter(self.state).servable(e.sha256))
        self.assertLess(time.monotonic() - t0, 4)
        holder.kill()
        holder.wait()


class OperatorIdentityTests(tdl.Base):
    BAD = [None, "", "   ", 123, "bad\nname", "x" * 500, "tab\there"]

    def test_every_mutation_rejects_a_missing_or_malformed_operator_and_changes_nothing(self):
        e, _ = self.ingest(V1)
        e2 = self.entry(V2)
        before = (self.state / "registry.json").read_bytes()
        for by in self.BAD:
            for name, call in {
                "ingest": lambda b: self.lc.ingest(e2, self.corpus, by=b),
                "approve": lambda b: self.lc.approve(e.id, 1, by=b),
                "reject": lambda b: self.lc.reject(e.id, 1, by=b),
                "withdraw": lambda b: self.lc.withdraw(e.id, 1, by=b),
                "rollback": lambda b: self.lc.rollback(e.id, 1, by=b),
                "audit_adopt": lambda b: self.lc.adopt_audit_chain(b),
            }.items():
                with self.subTest(by=by, op=name):
                    with self.assertRaises(dl.LifecycleError):
                        call(by)
        self.assertEqual((self.state / "registry.json").read_bytes(), before)
        self.assertEqual(self.lc.load()["sources"][e.id]["versions"]["1"]["state"], "pending")

    def test_the_name_is_recorded_as_supplied_and_marked_unauthenticated(self):
        e, _ = self.ingest(V1)
        self.lc.approve(e.id, 1, by="Ravi K. (Legal Ops)", note="reviewed")
        reg = self.lc.load()
        ev = [x for x in reg["events"] if x["op"] == "approve"][0]
        self.assertEqual((ev["by"], ev["note"], ev["identity_assurance"]), ("Ravi K. (Legal Ops)", "reviewed", dl.ASSURANCE))
        self.assertEqual(ev["previous_state"], "pending")
        self.assertEqual(ev["new_state"], "approved")
        self.assertIn("not established", ev["legal_approval"])
        self.assertEqual(reg["sources"][e.id]["versions"]["1"]["history"][-1]["by"], "Ravi K. (Legal Ops)")
        self.assertTrue(all(x["identity_assurance"] == dl.ASSURANCE for x in reg["events"]))
        self.assertIn("unauthenticated", dl.ASSURANCE)

    def test_the_module_defines_no_default_operator_and_the_cli_requires_one(self):
        import inspect
        src = inspect.getsource(dl)
        for needle in ('by="admin"', "by='admin'", 'by="system"', 'by="root"'):
            self.assertNotIn(needle, src)
        with self.assertRaises(SystemExit):
            dl.main(["--state-dir", str(self.state), "--db-dir", str(self.db), "withdraw", "src", "1"], out=lambda *_: None)

    def test_every_transition_event_carries_the_required_audit_fields(self):
        e = self.approve_v1()
        self.ingest(V2)
        self.lc.approve(e.id, 2, by="r", note="amendment")
        self.lc.rollback(e.id, 1, by="r", note="undo")
        self.lc.withdraw(e.id, 1, by="r", note="repealed")
        for ev in self.lc.load()["events"]:
            for k in ("seq", "at", "op", "source", "version", "by", "note", "previous_state", "new_state", "prev", "hash"):
                self.assertIn(k, ev, ev["op"])
        ops = [(x["op"], x["previous_state"], x["new_state"]) for x in self.lc.load()["events"]]
        self.assertIn(("supersede", "approved", "superseded"), ops)
        self.assertIn(("rollback", "superseded", "approved"), ops)
        self.assertIn(("withdraw", "approved", "withdrawn"), ops)
        self.assertEqual(self.lc.audit_check(), [])


class AuditIntegrityTests(tdl.Base):
    def setUp(self):
        super().setUp()
        self.e = self.approve_v1()
        self.ingest(V2)
        self.lc.approve(self.e.id, 2, by="r", note="n")
        self.reg_path = self.state / "registry.json"
        self.assertEqual(self.lc.audit_check(), [])

    def edit(self, fn):
        reg = json.loads(self.reg_path.read_text())
        fn(reg)
        self.reg_path.write_text(json.dumps(reg, indent=1, sort_keys=True))

    def assert_fail_closed(self, fragment=None):
        problems = self.lc.audit_check()
        self.assertTrue(problems)
        if fragment:
            self.assertIn(fragment, " ".join(problems))
        with self.assertRaises(dl.LifecycleError) as cm:
            self.lc.withdraw(self.e.id, 2, by="r")
        self.assertIn("audit integrity failure", str(cm.exception))
        self.assertFalse(dl.ServeFilter(self.state).servable(self.entry(V2).sha256))   # nothing is served
        self.assertTrue(any(p.startswith("audit:") for p in self.lc.verify()))

    def test_an_altered_event_is_detected(self):
        self.edit(lambda r: r["events"][1].update(note="forged reason"))
        self.assert_fail_closed("event 1")

    def test_a_removed_event_is_detected(self):
        self.edit(lambda r: r["events"].pop(2))
        self.assert_fail_closed()

    def test_a_reordered_event_is_detected(self):
        self.edit(lambda r: r["events"].insert(1, r["events"].pop(3)))
        self.assert_fail_closed()

    def test_an_inserted_event_is_detected(self):
        self.edit(lambda r: r["events"].insert(2, dict(r["events"][2], note="extra")))
        self.assert_fail_closed()

    def test_an_edit_that_recomputes_the_chain_is_still_caught_by_the_mirror(self):
        def rewrite(r):
            r["events"][0]["note"] = "rewritten"
            prev = dl.GENESIS
            for e in r["events"]:
                e["prev"] = prev
                e["hash"] = dl._event_hash(e)
                prev = e["hash"]
        self.edit(rewrite)
        self.assert_fail_closed("mirror")

    def test_truncating_the_registry_history_is_caught_by_the_mirror(self):
        self.edit(lambda r: r["events"].pop())
        self.assert_fail_closed("more events than the registry")

    def test_a_malformed_mirror_fails_closed(self):
        with open(self.state / "audit.jsonl", "a") as f:
            f.write("{not json\n")
        self.assert_fail_closed("unreadable")

    def test_malformed_event_types_fail_closed(self):
        self.edit(lambda r: r.update(events=["junk"]))
        self.assert_fail_closed()
        self.edit(lambda r: r.update(events="junk"))
        self.assertTrue(self.lc.audit_check())

    def test_a_lagging_mirror_after_a_crash_is_resynchronised_not_an_error(self):
        mirror = self.state / "audit.jsonl"
        lines = mirror.read_text().splitlines()
        mirror.write_text("\n".join(lines[:-2]) + "\n")                 # a crash before the last two lines were appended
        self.assertEqual(self.lc.audit_check(), [])
        self.lc.withdraw(self.e.id, 2, by="r")
        self.assertEqual(len(mirror.read_text().splitlines()), len(self.lc.load()["events"]))
        self.assertEqual(self.lc.audit_check(), [])

    def test_recover_and_read_only_commands_still_work_when_the_audit_is_broken(self):
        self.edit(lambda r: r["events"][1].update(note="forged"))
        self.assertEqual(self.lc.recover("op")["action"], "none")
        self.lc.status()
        self.lc.warning_coverage()

    def test_a_registry_from_before_the_chain_existed_is_adopted_once_explicitly(self):
        def strip(r):
            for e in r["events"]:
                for k in ("seq", "prev", "hash", "previous_state", "new_state", "identity_assurance"):
                    e.pop(k, None)
        self.edit(strip)
        (self.state / "audit.jsonl").unlink()
        self.assertIn("legacy", " ".join(self.lc.audit_check()))
        with self.assertRaises(dl.LifecycleError):
            self.lc.withdraw(self.e.id, 2, by="r")
        self.assertFalse(dl.ServeFilter(self.state).servable(self.entry(V2).sha256))
        n = len(self.lc.load()["events"])
        out = self.lc.adopt_audit_chain("operator-x", "migrate")
        self.assertEqual(out["adopted_events"], n)
        self.assertEqual(self.lc.audit_check(), [])
        reg = self.lc.load()
        self.assertTrue(all(e.get("legacy") for e in reg["events"][:n]))
        last = reg["events"][-1]
        self.assertEqual((last["op"], last["by"]), ("audit_adopt", "operator-x"))
        self.assertIn("not tamper-evident", last["caveat"])
        self.assertTrue(dl.ServeFilter(self.state).servable(self.entry(V2).sha256))
        with self.assertRaises(dl.LifecycleError):
            self.lc.adopt_audit_chain("operator-x")                       # only once
        self.lc.withdraw(self.e.id, 2, by="r")

    def test_a_mixture_of_chained_and_unchained_events_is_never_adopted(self):
        self.edit(lambda r: [r["events"][0].pop(k) for k in ("seq", "prev", "hash")])
        self.assertTrue(self.lc.audit_check())
        with self.assertRaises(dl.LifecycleError):
            self.lc.adopt_audit_chain("op")


def hashlib_sha(text):
    import hashlib
    return hashlib.sha256(text.encode()).hexdigest()


class WarningIntegrationTests(tdl.Base):
    def status_file(self, entries, name="status.json"):
        path = self.tmp / name
        path.write_text(json.dumps({"schema_version": 1, "jurisdiction": "Telangana", "note": "fixture", "entries": [
            {"manifest_id": e.get("id", "tmvr-fixture"), "file": e.get("file", "rules.txt"), "sha256": e["sha256"],
             "status": e.get("status", "unverified_snapshot"), "label": "Fixture Rules",
             "related_instruments": e.get("related", []), "decision_refs": e.get("refs", []),
             "evidence": [{"file": e.get("file", "rules.txt"), "sha256": e["sha256"], "note": "fixture"}],
             "assigned_by": "test fixture", "review": {"reviewer": None, "review_date": None, "decision": None, "rationale": None},
             "provision_overrides": []} for e in entries]}))
        return path

    def with_status(self, path):
        lc = self.make()
        lc.source_status_file = path
        return lc

    def test_a_new_version_without_an_entry_is_refused_unless_knowingly_accepted_and_the_override_is_audited(self):
        e1 = self.entry(V1)
        lc = self.with_status(self.status_file([{"sha256": e1.sha256}]))
        lc.ingest(e1, self.corpus, by="r")
        out = lc.approve(e1.id, 1, by="r")
        self.assertEqual(out["warning_coverage"]["coverage"], "covered")
        e2 = self.entry(V2)
        lc.ingest(e2, self.corpus, by="r")
        with self.assertRaises(dl.LifecycleError) as cm:
            lc.approve(e1.id, 2, by="r")
        self.assertIn("warning metadata is missing", str(cm.exception))
        self.assertEqual(lc.status()[e1.id]["versions"]["2"], "pending")
        self.assertEqual(self.hashes(), {e1.sha256})
        out = lc.approve(e1.id, 2, by="r", accept_missing_status=True, note="entry follows review")
        ev = [x for x in lc.load()["events"] if x["op"] == "approve"][-1]
        self.assertEqual((ev["warning_coverage"], ev["status_override_accepted"]), ("missing", True))

    def test_an_amended_version_never_inherits_the_predecessors_entry(self):
        e1 = self.entry(V1)
        lc = self.with_status(self.status_file([{"sha256": e1.sha256, "status": "known_amendments_unresolved",
                                                  "related": ["G.O.Ms.No. 1"]}]))
        lc.ingest(e1, self.corpus, by="r")
        lc.approve(e1.id, 1, by="r")
        e2 = self.entry(V2)
        lc.ingest(e2, self.corpus, by="r")
        cov = {(v["version"]): v for v in lc.warning_coverage()["versions"]}
        self.assertEqual(cov[1]["coverage"], "covered")
        self.assertEqual(cov[2]["coverage"], "missing")
        self.assertTrue(any("NOT inherited" in f for f in cov[2]["findings"]))
        self.assertIsNone(cov[2]["status"])

    def test_an_identical_copied_entry_is_flagged_for_a_applicability_check(self):
        e1 = self.entry(V1)
        sha2 = hashlib_sha(V2)
        lc = self.with_status(self.status_file([{"sha256": e1.sha256, "status": "known_amendments_unresolved", "related": ["X"]},
                                                 {"sha256": sha2, "file": "rules-v2.txt", "status": "known_amendments_unresolved",
                                                  "related": ["X"]}]))
        lc.ingest(e1, self.corpus, by="r")
        lc.approve(e1.id, 1, by="r")
        e2 = self.entry(V2, name="rules-v2.txt")
        lc.ingest(e2, self.corpus, by="r")
        v2 = [v for v in lc.warning_coverage()["versions"] if v["version"] == 2][0]
        self.assertEqual(v2["coverage"], "covered")
        self.assertTrue(any("identical to the predecessor" in f for f in v2["findings"]))

    def test_superseded_and_withdrawn_versions_are_reported_as_not_served(self):
        e1 = self.entry(V1)
        lc = self.with_status(self.status_file([{"sha256": e1.sha256}, {"sha256": hashlib_sha(V2), "file": "rules-v2.txt"}]))
        lc.ingest(e1, self.corpus, by="r")
        lc.approve(e1.id, 1, by="r")
        e2 = self.entry(V2, name="rules-v2.txt")
        lc.ingest(e2, self.corpus, by="r")
        lc.approve(e1.id, 2, by="r")
        lc.withdraw(e1.id, 2, by="r")
        cov = {v["version"]: v for v in lc.warning_coverage()["versions"]}
        self.assertEqual((cov[1]["state"], cov[2]["state"]), ("superseded", "withdrawn"))
        self.assertFalse(cov[1]["served"] or cov[2]["served"])
        self.assertTrue(all(any("not served" in f for f in c["findings"]) for c in cov.values()))
        self.assertEqual({v["sha256"] for v in lc.warning_coverage()["versions"]}, {e1.sha256, e2.sha256})

    def test_ambiguous_metadata_is_surfaced(self):
        e1 = self.entry(V1)
        lc = self.with_status(self.status_file([{"sha256": e1.sha256, "id": "some-other-source"}]))
        lc.ingest(e1, self.corpus, by="r")
        cov = lc.warning_coverage()["versions"][0]
        self.assertEqual(cov["coverage"], "ambiguous")
        with self.assertRaises(dl.LifecycleError):
            lc.approve(e1.id, 1, by="r")
        lc2 = self.with_status(self.status_file([{"sha256": e1.sha256, "file": "other-name.txt"}], "s2.json"))
        self.assertEqual(lc2.warning_coverage()["versions"][0]["coverage"], "ambiguous")

    def test_an_unavailable_or_invalid_registry_is_surfaced_and_blocks_approval(self):
        e1 = self.entry(V1)
        lc = self.make()
        lc.ingest(e1, self.corpus, by="r")
        for path in (self.tmp / "missing.json", self.tmp / "bad.json"):
            if path.name == "bad.json":
                path.write_text('{"schema_version": 1, "entries": []}')
            cov = self.with_status(path).warning_coverage()
            self.assertEqual(cov["versions"][0]["coverage"], "registry_unavailable")
            self.assertTrue(cov["registry_errors"])
            with self.assertRaises(dl.LifecycleError):
                self.with_status(path).approve(e1.id, 1, by="r")

    def test_registry_entries_without_a_version_are_listed_as_orphans(self):
        e1 = self.entry(V1)
        lc = self.with_status(self.status_file([{"sha256": e1.sha256}, {"sha256": "e" * 64, "id": "unknown-doc",
                                                                         "file": "unknown.txt"}]))
        lc.ingest(e1, self.corpus, by="r")
        self.assertEqual([o["sha256"] for o in lc.warning_coverage()["orphan_registry_entries"]], ["e" * 64])

    def test_without_a_configured_registry_behaviour_is_unchanged(self):
        e1, _ = self.ingest(V1)
        out = self.lc.approve(e1.id, 1, by="r")
        self.assertIsNone(out["warning_coverage"])

    def test_the_registry_cannot_hold_two_entries_for_one_file_name_so_a_same_name_amendment_needs_its_entry_replaced(self):
        # Finding, pinned: source_status.parse rejects duplicate file names. An amended file that keeps its name therefore
        # cannot have the old and the new entry side by side; coverage reports the registry as unavailable, never as covered.
        e1 = self.entry(V1)
        lc = self.with_status(self.status_file([{"sha256": e1.sha256}, {"sha256": hashlib_sha(V2)}]))
        lc.ingest(e1, self.corpus, by="r")
        cov = lc.warning_coverage()
        self.assertEqual(cov["versions"][0]["coverage"], "registry_unavailable")
        self.assertIn("duplicates file name", " ".join(cov["registry_errors"]))

    def test_the_real_source_status_registry_parses_and_names_every_enrolled_hash(self):
        real = ROOT / "legal-status" / "source-status.json"
        if not real.is_file():
            self.skipTest("no source-status registry in this checkout")
        by_hash, errors = self.make()._load_status_registry(real)
        self.assertEqual(errors, [])
        self.assertEqual(len(by_hash), 23)  # 20 Telangana sources plus the 3 separately tagged Central sources


class ApprovalBoundaryTests(tlb.BootBase):
    """The Stage 6B boundary is unchanged by 6C."""

    def test_quarantine_and_idempotence_still_hold_under_the_lock(self):
        self.lc.bootstrap("op", None, allow_quarantine=True)
        first = (self.state / "registry.json").read_bytes()
        again = self.lc.bootstrap("op", None, allow_quarantine=True)
        self.assertEqual(again["result"], {"registered": 0, "upgraded": 0, "unchanged": 3})
        self.assertEqual((self.state / "registry.json").read_bytes(), first)
        self.assertEqual(self.servable(), set())
        with self.assertRaises(dl.LifecycleError):
            self.lc.approve("src-a", 1, by="op")                          # quarantined: needs an approval basis via bootstrap
        self.assertEqual(self.lc.audit_check(), [])
        ev = self.lc.load()["events"][0]
        self.assertEqual((ev["op"], ev["new_state"], ev["identity_assurance"]), ("bootstrap", "pending", dl.ASSURANCE))

    def test_hash_and_status_registry_identity_alone_never_approve(self):
        plan = self.lc.plan_bootstrap(None, self.corpus, self.status_file())
        self.assertEqual(plan["totals"]["verified"], 0)
        self.lc.source_status_file = self.status_file()
        self.lc.bootstrap("op", None, source_status_file=self.status_file(), allow_quarantine=True)
        self.assertEqual(self.servable(), set())
        # only an explicit basis approves, and only the sources that also pass the status-registry check
        self.lc.bootstrap("op", tlb.BASIS, source_status_file=self.status_file(drop="src-b", wrong_id="src-c"),
                          allow_quarantine=True)
        self.assertEqual(self.servable(), {self.entries["src-a"].sha256})


class CacheAfterTransitionsTests(tdl.CacheIntegrationTests):
    """Re-run the Stage 6 cache cases on the hardened code (inherited tests) plus the supersede/audit interplay."""

    def test_the_registry_digest_changes_on_every_transition_including_audit_only_ones(self):
        e = self.approve_v1()
        seen = {self.flt.digest()}
        self.ingest(V2)
        seen.add(self.flt.digest())
        self.lc.approve(e.id, 2, by="r")
        seen.add(self.flt.digest())
        self.lc.rollback(e.id, 1, by="r")
        seen.add(self.flt.digest())
        self.lc.withdraw(e.id, 1, by="r")
        seen.add(self.flt.digest())
        self.assertEqual(len(seen), 5)


if __name__ == "__main__":
    unittest.main()
