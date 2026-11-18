"""Step 3 review M1 (decision register and evidence bound to the signed chain) and the interim "Option A" plausibility checks.

Everything is SYNTHETIC: throwaway Ed25519 keys made per test, invented placeholder names, temp directories only. No real
register, approval, registry, manifest, index or key is read for writing. Reviewer authentication (M2 "Option B") is NOT built
and nothing here claims it: the binding proves the approval authority attested these bytes, not that a named reviewer approved.
"""

import copy
import hashlib
import inspect
import json
import os
import stat
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
ROOT = Path(__file__).resolve().parent.parent

import test_provision_validity as tpv  # noqa: E402
import test_source_status_ledger_binding as tb  # noqa: E402
import validity_decisions_support as sup  # noqa: E402
from backend import evidence_manifest as em, ledger_acceptance as gate, provision_validity as pv  # noqa: E402
from backend import source_status as ss, validity_decisions as vd  # noqa: E402
from backend.source_status import LEDGER_KEY, MANIFEST_KEY, REGISTER_KEY  # noqa: E402

import test_source_status as tss  # noqa: E402

SHA = "ab12" * 16
OTHER = "cd34" * 16
TODAY = tb.dt.date(2026, 11, 8)
# Absolute pins of the real files as they were when this work began. Nothing here may change them, and a later legitimate
# change to either file must update these two constants deliberately, in the same change.
REAL_REGISTRY_SHA256 = "cd463006b2df2928a624ce4f1aee8e60d7fd4d87f39f4c304fd10ca2f99431d6"       # legal-status/source-status.json
REAL_REGISTER_SHA256 = "a853ccde67f8e929fb940ad713345a83511294a83f698e1031e80ffd0580206e"        # the real Stage 22 decision register
REAL_REGISTRY_SHA_BEFORE = hashlib.sha256((ROOT / "legal-status" / "source-status.json").read_bytes()).hexdigest()
REAL_REGISTER_SHA_BEFORE = hashlib.sha256(sup.REAL_REGISTER.read_bytes()).hexdigest()


def tearDownModule():
    assert hashlib.sha256((ROOT / "legal-status" / "source-status.json").read_bytes()).hexdigest() == REAL_REGISTRY_SHA256
    assert hashlib.sha256(sup.REAL_REGISTER.read_bytes()).hexdigest() == REAL_REGISTER_SHA256


def led():
    return tpv.with_closer("delete", link=True)


def sha_of(b):
    return hashlib.sha256(b).hexdigest()


# ------------------------------------------------------------------------------------------------ registry keys

class RegistryKeyTests(unittest.TestCase):
    def reg(self, **kw):
        d = tss.registry(tss.entry())
        d.update(kw)
        return d

    def test_the_new_keys_are_optional_and_validated_like_the_ledger_key(self):
        self.assertIsInstance(ss.parse(self.reg()), dict)
        self.assertIsInstance(ss.parse(self.reg(**{REGISTER_KEY: SHA, MANIFEST_KEY: OTHER, LEDGER_KEY: SHA})), dict)
        for key in (REGISTER_KEY, MANIFEST_KEY):
            for bad in ("", "BAD", SHA.upper(), SHA + "\n", SHA[:-1], 5, None, [SHA], True):
                with self.subTest(key=key, bad=bad), self.assertRaises(ss.SourceStatusError):
                    ss.parse(self.reg(**{key: bad}))

    def test_unknown_top_level_keys_are_still_rejected(self):
        with self.assertRaises(ss.SourceStatusError):
            ss.parse(self.reg(validity_other_sha256=SHA))

    def test_the_loader_exposes_the_keys_only_on_a_valid_registry(self):
        raw = json.dumps(self.reg(**{REGISTER_KEY: SHA, MANIFEST_KEY: OTHER})).encode()
        ok = ss.load_bytes(raw)
        self.assertEqual((ok.state, ok.validity_decision_register_sha256, ok.validity_evidence_manifest_sha256),
                         ("valid", SHA, OTHER))
        bad = ss.load_bytes(json.dumps(self.reg(**{REGISTER_KEY: "x"})).encode())
        self.assertEqual((bad.state, bad.validity_decision_register_sha256, bad.validity_evidence_manifest_sha256),
                         ("invalid", None, None))
        plain = ss.load_bytes(json.dumps(self.reg()).encode())
        self.assertEqual((plain.validity_decision_register_sha256, plain.validity_evidence_manifest_sha256), (None, None))

    def test_the_real_registry_is_unchanged_and_binds_nothing(self):
        text = (ROOT / "legal-status" / "source-status.json").read_text(encoding="utf-8")
        for key in (LEDGER_KEY, REGISTER_KEY, MANIFEST_KEY):
            self.assertNotIn(key, text)
        self.assertEqual(sha_of(text.encode("utf-8")), REAL_REGISTRY_SHA256)


class VerifyBindingTests(unittest.TestCase):
    def reg(self, which, bound=SHA, state="valid"):
        r = ss.Registry(state, [], "e" * 64, {})
        setattr(r, which, bound)
        return r

    def test_each_binding_accepts_only_the_exact_hash(self):
        for fn, attr in ((ss.verify_register_binding, "validity_decision_register_sha256"),
                         (ss.verify_manifest_binding, "validity_evidence_manifest_sha256")):
            self.assertEqual(fn(self.reg(attr), SHA), [])
            cases = [(self.reg(attr), OTHER), (self.reg(attr, None), SHA), (self.reg(attr, state="invalid"), SHA),
                     (self.reg(attr, state="absent"), SHA), (self.reg(attr, "BAD"), SHA), (self.reg(attr, SHA.upper()), SHA),
                     (self.reg(attr), SHA.upper()), (self.reg(attr), SHA + "\n"), (self.reg(attr), None), (self.reg(attr), b"1" * 64),
                     (None, SHA), (object(), SHA)]
            for r, sha in cases:
                with self.subTest(fn=fn.__name__, r=r, sha=sha):
                    self.assertTrue(fn(r, sha))

    def test_a_binding_does_not_stand_in_for_another(self):
        r = self.reg("validity_decision_register_sha256")
        self.assertTrue(ss.verify_manifest_binding(r, SHA))
        self.assertTrue(ss.verify_ledger_binding(r, SHA))


# ------------------------------------------------------------------------------------------------ canonical manifest

def manifest(files=None, **over):
    obj = {"schema_version": 1, "jurisdiction": "Telangana",
           "files": files if files is not None else [{"path": "evidence/a.txt", "sha256": SHA, "size": 3}]}
    obj.update(over)
    return obj


class ManifestFormatTests(unittest.TestCase):
    def rejected(self, raw, fragment=None):
        with self.assertRaises(em.ManifestError) as cm:
            em.parse(raw)
        if fragment:
            self.assertIn(fragment, str(cm.exception))

    def test_a_canonical_manifest_parses_and_round_trips(self):
        raw = em.canonical_bytes(manifest())
        m = em.parse(raw)
        self.assertEqual((m.jurisdiction, m.files), ("Telangana", (("evidence/a.txt", SHA, 3),)))
        self.assertEqual(em.canonical_bytes(json.loads(raw)), raw)

    def test_serialisation_is_deterministic_whatever_the_insertion_order(self):
        a = {"files": [{"size": 3, "sha256": SHA, "path": "a"}], "schema_version": 1, "jurisdiction": "Telangana"}
        b = {"schema_version": 1, "jurisdiction": "Telangana", "files": [{"path": "a", "sha256": SHA, "size": 3}]}
        self.assertEqual(em.canonical_bytes(a), em.canonical_bytes(b))
        self.assertEqual(sha_of(em.canonical_bytes(a)), sha_of(em.canonical_bytes(b)))
        self.assertEqual(em.canonical_bytes(a),
                         b'{"files":[{"path":"a","sha256":"' + SHA.encode() + b'","size":3}],"jurisdiction":"Telangana","schema_version":1}')

    def test_the_test_helper_and_the_module_agree_on_the_canonical_form(self):
        files = {"evidence/a.txt": b"abc", "b.txt": b"x"}
        self.assertEqual(sup.manifest_bytes(files), em.canonical_bytes(sup.manifest_obj(files)))

    def test_non_canonical_serialisations_of_a_valid_manifest_are_refused(self):
        obj = manifest()
        canon = em.canonical_bytes(obj)
        variants = {
            "pretty printed": json.dumps(obj, indent=2, sort_keys=True).encode(),
            "spaces after separators": json.dumps(obj, sort_keys=True).encode(),
            "trailing newline": canon + b"\n",
            "leading space": b" " + canon,
            "unsorted keys": json.dumps(obj, separators=(",", ":")).encode() if list(obj) != sorted(obj) else None,
            "byte order mark": b"\xef\xbb\xbf" + canon,
            "raw non-ascii": em.canonical_bytes(manifest(jurisdiction="Telangana")).replace(b"Telangana", "Telanganá".encode()),
            "escaped letter": canon.replace(b"Telangana", b"Telangan\\u0061"),
        }
        for name, raw in variants.items():
            if raw is None:
                continue
            with self.subTest(name):
                self.rejected(raw)

    def test_malformed_manifests_are_refused(self):
        good = manifest()
        cases = {
            "not json": b"{", "empty": b"", "array": b"[]", "null": b"null", "bad utf-8": b"\xff\xfe",
            "duplicate keys": b'{"files":[],"files":[],"jurisdiction":"Telangana","schema_version":1}',
            "nan": b'{"files":[],"jurisdiction":"Telangana","schema_version":NaN}',
            "deep": b"[" * 100000 + b"]" * 100000,
            "extra key": em.canonical_bytes({**good, "note": "x"}),
            "missing key": em.canonical_bytes({"files": [], "schema_version": 1}),
            "schema 2": em.canonical_bytes(manifest(schema_version=2)),
            "schema true": em.canonical_bytes(manifest(schema_version=True)),
            "blank jurisdiction": em.canonical_bytes(manifest(jurisdiction=" ")),
            "files not a list": em.canonical_bytes(manifest(files={})),
            "entry extra key": em.canonical_bytes(manifest([{"path": "a", "sha256": SHA, "size": 1, "x": 1}])),
            "entry missing key": em.canonical_bytes(manifest([{"path": "a", "sha256": SHA}])),
            "uppercase sha": em.canonical_bytes(manifest([{"path": "a", "sha256": SHA.upper(), "size": 1}])),
            "short sha": em.canonical_bytes(manifest([{"path": "a", "sha256": SHA[:-1], "size": 1}])),
            "float size": b'{"files":[{"path":"a","sha256":"' + SHA.encode() + b'","size":1.0}],"jurisdiction":"Telangana","schema_version":1}',
            "negative size": em.canonical_bytes(manifest([{"path": "a", "sha256": SHA, "size": -1}])),
            "bool size": em.canonical_bytes(manifest([{"path": "a", "sha256": SHA, "size": True}])),
            "string size": em.canonical_bytes(manifest([{"path": "a", "sha256": SHA, "size": "1"}])),
            "huge size": em.canonical_bytes(manifest([{"path": "a", "sha256": SHA, "size": em.MAX_FILE_BYTES + 1}])),
            "duplicate path": em.canonical_bytes(manifest([{"path": "a", "sha256": SHA, "size": 1}] * 2)),
            "case duplicate": em.canonical_bytes(manifest([{"path": "A", "sha256": SHA, "size": 1}, {"path": "a", "sha256": SHA, "size": 1}])),
            "unsorted paths": em.canonical_bytes(manifest([{"path": "b", "sha256": SHA, "size": 1}, {"path": "a", "sha256": SHA, "size": 1}])),
        }
        for bad in ("../x", "/x", "a/../b", "a//b", "a/./b", "a\\b", "", "a\0b", "C:x", "a/", "café", "a\nb", " a", "a ", "x" * 300):
            cases[f"path {bad!r}"] = em.canonical_bytes(manifest([{"path": bad, "sha256": SHA, "size": 1}]))
        for name, raw in cases.items():
            with self.subTest(name):
                self.rejected(raw)

    def test_size_limits(self):
        self.rejected(b" " * (em.MAX_MANIFEST_BYTES + 1), "too large")
        many = [{"path": f"f{i:05d}", "sha256": SHA, "size": 1} for i in range(em.MAX_FILES + 1)]
        self.rejected(em.canonical_bytes(manifest(many)))

    def test_only_bytes_are_parsed(self):
        for bad in (None, "{}", 5, [], {}):
            with self.subTest(bad=bad):
                self.rejected(bad)

    def test_an_empty_file_list_is_a_valid_manifest(self):
        self.assertEqual(em.parse(em.canonical_bytes(manifest([]))).files, ())


class VerifyFilesTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.root = Path(self._t.name) / "held"
        self.files = {"evidence/a.txt": b"alpha", "b.txt": b"beta"}
        sup.write_evidence(self.root, self.files)
        self.m = em.parse(sup.manifest_bytes(self.files))

    def verify(self, names=None):
        return em.verify_files(self.m, str(self.root), names if names is not None else list(self.files))

    def test_genuine_files_are_held(self):
        problems, held = self.verify()
        self.assertEqual((problems, held), ([], {k: sha_of(v) for k, v in self.files.items()}))

    def test_a_name_not_in_the_manifest_is_refused_even_if_the_file_exists(self):
        (self.root / "extra.txt").write_bytes(b"x")
        problems, held = self.verify(["extra.txt"])
        self.assertEqual(held, {})
        self.assertIn("not in the signed evidence manifest", problems[0])

    def test_same_size_replacement_is_refused(self):
        (self.root / "b.txt").write_bytes(b"BETA")
        problems, held = self.verify(["b.txt"])
        self.assertEqual(held, {})
        self.assertIn("does not match the manifest SHA-256", problems[0])

    def test_size_change_is_refused(self):
        (self.root / "b.txt").write_bytes(b"beta and more")
        self.assertIn("different size", self.verify(["b.txt"])[0][0])

    def test_missing_directory_or_non_regular_files_are_refused(self):
        (self.root / "b.txt").unlink()
        (self.root / "b.txt").mkdir()
        self.assertTrue(self.verify(["b.txt"])[0])
        self.assertEqual(self.verify(["evidence"])[1], {})                       # a directory is not a file
        problems, held = em.verify_files(self.m, str(self.root / "nowhere"), ["b.txt"])
        self.assertEqual(held, {})
        self.assertIn("cannot be opened", problems[0])

    def test_links_are_refused_wherever_they_point(self):
        outside = Path(self._t.name) / "outside.txt"
        outside.write_bytes(b"beta")
        (self.root / "b.txt").unlink()
        (self.root / "b.txt").symlink_to(outside)                              # file link out of the directory
        self.assertEqual(self.verify(["b.txt"])[1], {})
        (self.root / "b.txt").unlink()
        (self.root / "real.txt").write_bytes(b"beta")
        (self.root / "b.txt").symlink_to(self.root / "real.txt")               # file link that stays inside
        self.assertEqual(self.verify(["b.txt"])[1], {})
        moved = Path(self._t.name) / "moved"
        os.rename(self.root / "evidence", moved)
        (self.root / "evidence").symlink_to(moved)                             # directory link
        self.assertEqual(self.verify(["evidence/a.txt"])[1], {})

    def test_a_file_swapped_for_a_link_between_listing_and_open_is_not_followed(self):
        outside = Path(self._t.name) / "outside.txt"
        outside.write_bytes(b"beta")
        real_open = os.open

        def swapping(path, flags, *a, **k):
            if path == "b.txt" and "dir_fd" in k:
                (self.root / "b.txt").unlink()
                (self.root / "b.txt").symlink_to(outside)
            return real_open(path, flags, *a, **k)

        with mock.patch.object(os, "open", swapping), mock.patch.object(os, "supports_dir_fd", {swapping}):
            problems, held = self.verify(["b.txt"])
        self.assertEqual(held, {})

    def test_a_fifo_never_blocks(self):
        (self.root / "b.txt").unlink()
        os.mkfifo(self.root / "b.txt")
        problems, held = self.verify(["b.txt"])
        self.assertEqual(held, {})
        self.assertTrue(problems)

    def test_a_file_that_grows_while_hashed_is_not_held(self):
        real_fdopen = os.fdopen

        def growing(fd, *a, **k):
            fh = real_fdopen(fd, *a, **k)
            if "b.txt" in os.readlink(f"/dev/fd/{fd}") if os.path.exists("/dev/fd") else False:
                (self.root / "b.txt").write_bytes(b"beta" + b"x" * 100)
            return fh

        with mock.patch.object(os, "fdopen", growing):
            problems, held = self.verify(["b.txt"])
        self.assertNotIn("b.txt", held)

    def test_every_name_is_checked_not_only_the_first_failure(self):
        (self.root / "b.txt").write_bytes(b"BETA")
        problems, held = self.verify()
        self.assertEqual(sorted(held), ["evidence/a.txt"])
        self.assertEqual(len(problems), 1)

    def test_unsafe_names_are_refused(self):
        for bad in ("../x", "/etc/hosts", "a\\b", "", "a//b", None, 5):
            with self.subTest(bad=bad):
                problems, held = self.verify([bad]) if isinstance(bad, str) else (None, em.verify_files(self.m, str(self.root), [bad])[1])
                self.assertEqual(held, {})

    def test_a_platform_without_safe_opens_fails_closed(self):
        with mock.patch.object(os, "supports_dir_fd", set()):
            problems, held = self.verify()
        self.assertEqual(held, {})
        self.assertIn("cannot be verified safely", problems[0])


# ------------------------------------------------------------------------------------------------ the gate

class GateBindingTests(tb.GateCase):
    def chain(self, ledger=None, **kw):
        return tb.make_chain(self._tmp.name, led() if ledger is None else ledger, **kw)

    def test_a_genuine_chain_is_accepted_and_reports_both_hashes(self):
        c = self.chain()
        a = tb.run(c)
        self.assertTrue(a.ok, a.problems)
        self.assertEqual((a.register_sha256, a.manifest_sha256), (sha_of(c.register.read_bytes()), sha_of(c.manifest.read_bytes())))
        reg = json.loads(c.registry.read_text())
        self.assertEqual((reg[REGISTER_KEY], reg[MANIFEST_KEY]), (a.register_sha256, a.manifest_sha256))

    def test_the_manifest_path_is_required_and_keyword_only(self):
        params = inspect.signature(gate.accept_ledger).parameters
        self.assertIs(params["evidence_manifest"].default, inspect.Parameter.empty)
        self.assertEqual(params["evidence_manifest"].kind, inspect.Parameter.KEYWORD_ONLY)
        c = self.chain()
        with self.assertRaises(TypeError):
            gate.accept_ledger(c.ledger, registry_path=c.registry, approval_path=c.approval, trusted_keys=c.keys,
                               decision_register=c.register, metadatas=c.metadatas, evidence_dir=c.evidence)

    def test_the_registry_must_bind_both_files(self):
        for key, fragment in ((REGISTER_KEY, "does not bind a validity decision register"),
                              (MANIFEST_KEY, "does not bind a validity evidence manifest")):
            with self.subTest(key=key):
                self.assertRejected(tb.run(self.chain(registry_mut=lambda r, k=key: r.pop(k))), fragment)

    def test_wrong_or_malformed_bindings_are_rejected(self):
        self.assertRejected(tb.run(self.chain(register_bound=OTHER)), "validity decision register has changed since the registry bound it")
        self.assertRejected(tb.run(self.chain(manifest_bound=OTHER)), "validity evidence manifest has changed since the registry bound it")
        for bad in (SHA.upper(), "x", ""):
            self.assertFalse(tb.run(self.chain(register_bound=bad)).ok)
            self.assertFalse(tb.run(self.chain(manifest_bound=bad)).ok)

    # ---- the decision register

    def edited_register(self, mutate):
        c = self.chain()
        reg = json.loads(c.register.read_text())
        mutate(reg)
        c.register.write_text(json.dumps(reg))
        return c

    def test_editing_the_register_after_signing_is_rejected(self):
        for name, mutate in {
            "status changed": lambda r: r["decisions"][0].update(status="pending"),
            "reviewer renamed": lambda r: r["decisions"][0]["reviewer"].update(name="Reviewer Gamma"),
            "decision text": lambda r: r["decisions"][0].update(decision="something else"),
            "history added": lambda r: r["decisions"][0]["history"].append({"date": "2026-01-03", "status": "approved", "by": "x"}),
            "record removed": lambda r: r["decisions"].pop(),
            "key added": lambda r: r.update(note="harmless"),
        }.items():
            with self.subTest(name):
                a = tb.run(self.edited_register(mutate))
                self.assertRejected(a, "validity decision register has changed since the registry bound it")

    def test_a_pending_decision_cannot_be_turned_into_an_approved_one_by_editing_the_register(self):
        c = self.chain(register_mut=lambda r: r["decisions"][0].update(status="pending"))     # honest: the register says pending
        self.assertFalse(tb.run(c).ok)
        _, approved, _ = sup.decorate(led())                                                    # the attacker writes the approved text
        c.register.write_text(json.dumps(approved))
        self.assertRejected(tb.run(c), "has changed since the registry bound it")

    def test_byte_level_changes_that_keep_the_same_meaning_are_still_rejected(self):
        c = self.chain()
        original = c.register.read_bytes()
        for name, raw in {"trailing newline": original + b"\n", "reindented": json.dumps(json.loads(original), indent=2).encode(),
                          "keys reordered": json.dumps(json.loads(original), sort_keys=True).encode()}.items():
            c.register.write_bytes(raw)
            with self.subTest(name):
                self.assertRejected(tb.run(c), "has changed since the registry bound it")
        c.register.write_bytes(original)
        self.assertTrue(tb.run(c).ok)

    def test_substituting_another_chains_register_is_rejected(self):
        c, other = self.chain(), self.chain(tpv.one())
        self.assertRejected(tb.run(c, decision_register=other.register), "has changed since the registry bound it")

    def test_an_older_register_replayed_against_a_newer_ledger_is_rejected(self):
        old = self.chain()
        new = self.chain(register_mut=lambda r: r["decisions"][0]["history"][0].update(date="2025-12-31"))
        self.assertTrue(tb.run(old).ok and tb.run(new).ok)
        self.assertRejected(tb.run(new, decision_register=old.register), "has changed since the registry bound it")

    def test_forged_reviewer_names_cannot_be_written_into_a_signed_chain_afterwards(self):
        c = self.edited_register(lambda r: r["decisions"][0]["reviewer"].update(name="Reviewer Epsilon"))
        self.assertRejected(tb.run(c), "has changed since the registry bound it")

    def test_rewriting_the_registry_to_bind_new_files_breaks_the_approval(self):
        c = self.edited_register(lambda r: r["decisions"][0].update(status="pending"))
        reg = json.loads(c.registry.read_text())
        reg[REGISTER_KEY] = sha_of(c.register.read_bytes())
        c.registry.write_text(json.dumps(reg))
        self.assertRejected(tb.run(c), "is not the one the approval record binds")

    def test_the_register_is_read_as_a_regular_file_with_a_size_limit(self):
        c = self.chain()
        with mock.patch.object(gate, "MAX_REGISTER_BYTES", 10):
            self.assertRejected(tb.run(c), "cannot read the decision register")
        fifo = c.dir / "fifo"
        os.mkfifo(fifo)
        self.assertRejected(tb.run(c, decision_register=fifo), "cannot read the decision register")

    # ---- the registry and the ledger are read as regular files too (N3)

    def test_the_registry_and_ledger_are_read_as_regular_files_with_a_size_limit(self):
        for label, cap, over, fragment in (("registry", "MAX_REGISTRY_BYTES", "registry_path", "cannot read the source-status registry"),
                                           ("ledger", "MAX_LEDGER_BYTES", "ledger_path", "cannot read the ledger")):
            c = self.chain()
            with self.subTest(label, case="oversized"):
                with mock.patch.object(gate, cap, 10):
                    self.assertRejected(tb.run(c), fragment)
            with self.subTest(label, case="fifo"):
                fifo = c.dir / f"{label}-fifo"
                os.mkfifo(fifo)
                self.assertRejected(tb.run(c, **{over: fifo}), fragment)       # must return, not block
            with self.subTest(label, case="directory"):
                self.assertRejected(tb.run(c, **{over: c.dir}), fragment)
            with self.subTest(label, case="missing"):
                self.assertRejected(tb.run(c, **{over: c.dir / "missing"}), fragment)
            with self.subTest(label, case="still accepted when untouched"):
                self.assertTrue(tb.run(c).ok)

    def test_the_caps_leave_room_for_real_files(self):
        self.assertGreaterEqual(gate.MAX_REGISTRY_BYTES, 1 << 20)
        self.assertGreaterEqual(gate.MAX_LEDGER_BYTES, 1 << 20)

    def test_the_registry_and_ledger_are_each_read_exactly_once_through_the_safe_reader(self):
        c = self.chain()
        with tb.watch_reads(c.registry, c.ledger) as (safe, stray):
            a = tb.run(c)
        self.assertTrue(a.ok, a.problems)
        self.assertEqual(sorted(safe), sorted([str(c.registry), str(c.ledger)]))
        self.assertEqual(stray, [], "an extra read outside the safe reader")

    def test_a_registry_or_ledger_replaced_by_a_fifo_after_the_read_changes_nothing(self):
        for which in ("registry", "ledger"):
            with self.subTest(which):
                c = self.chain()
                target = str(getattr(c, which))
                real = em.read_regular_file

                def read_then_swap(path, limit, real=real, target=target):
                    data = real(path, limit)
                    if str(path) == target:
                        os.unlink(path)
                        os.mkfifo(path)
                    return data

                with mock.patch.object(em, "read_regular_file", read_then_swap):
                    self.assertTrue(tb.run(c).ok)
                self.assertTrue(stat.S_ISFIFO(os.stat(target).st_mode))          # the swap really happened

    # ---- a PENDING decision's cited evidence is checked by the gate itself (N1)
    # Only the gate's own evidence step can catch these: an unapproved decision's evidence is not examined by check_decisions.

    PENDING_FILE = "evidence/pending-note.txt"
    PENDING_BYTES = b"SYNTHETIC pending note. Not a legal source.\n"

    def pending_chain(self, cite=None, listed=True, on_disk=True):
        ledger = led()
        extra = copy.deepcopy(ledger["decisions"][0])
        extra.update(decision_id="LD-900", status="pending", reviewer=None, prepared_by=None, subject="pending, unused")
        ledger["decisions"].append(extra)
        cited = cite or self.PENDING_FILE

        def register_mut(reg):
            rec = reg["decisions"][-1]
            self.assertEqual(rec["status"], "pending")
            rec["supporting_sources"] = [{"file": cited, "sha256": sha_of(self.PENDING_BYTES), "location": "x", "kind": "instrument_text"}]

        def evidence_mut(files):
            if on_disk:
                files[self.PENDING_FILE] = self.PENDING_BYTES

        def manifest_mut(obj):
            if not listed:
                obj["files"] = [f for f in obj["files"] if f["path"] != self.PENDING_FILE]

        return self.chain(ledger, register_mut=register_mut, evidence_mut=evidence_mut, manifest_mut=manifest_mut)

    def assertEvidenceRejected(self, a, fragment):
        self.assertRejected(a, fragment)
        self.assertTrue(all(p.startswith("E1 evidence:") for p in a.problems), a.problems)    # the gate's own step, not a D-check

    def test_a_pending_decision_with_good_evidence_is_accepted(self):
        a = tb.run(self.pending_chain())
        self.assertTrue(a.ok, a.problems)

    def test_a_pending_decision_citing_an_unlisted_file_is_rejected_with_an_evidence_problem(self):
        self.assertEvidenceRejected(tb.run(self.pending_chain(listed=False)), "is not in the signed evidence manifest")

    def test_a_pending_decision_citing_a_tampered_file_is_rejected_with_an_evidence_problem(self):
        c = self.pending_chain()
        (c.evidence / self.PENDING_FILE).write_bytes(b"X" * len(self.PENDING_BYTES))
        self.assertEvidenceRejected(tb.run(c), "does not match the manifest SHA-256")
        (c.evidence / self.PENDING_FILE).write_bytes(self.PENDING_BYTES + b"more")
        self.assertEvidenceRejected(tb.run(c), "different size")

    def test_a_pending_decision_citing_a_missing_or_linked_file_is_rejected_with_an_evidence_problem(self):
        c = self.pending_chain()
        target = c.evidence / self.PENDING_FILE
        kept = c.dir / "kept-pending.txt"
        kept.write_bytes(self.PENDING_BYTES)                                   # outside, same bytes
        target.unlink()
        self.assertEvidenceRejected(tb.run(c), "cannot be opened below the evidence directory")
        target.symlink_to(kept)
        self.assertEvidenceRejected(tb.run(c), "cannot be opened below the evidence directory")

    def test_a_cited_name_that_differs_only_in_case_is_not_the_listed_file(self):
        # The file exists under its listed (lower-case) name, and macOS would open it under any case: the gate must not.
        c = self.pending_chain(cite=self.PENDING_FILE.upper())
        self.assertTrue((c.evidence / self.PENDING_FILE).is_file())
        self.assertEvidenceRejected(tb.run(c), "is not in the signed evidence manifest")
        self.assertIsNone(em.parse(c.manifest.read_bytes()).entry(self.PENDING_FILE.upper()))

    def test_an_approved_decision_citing_a_case_variant_of_a_listed_file_is_rejected(self):
        c = self.chain(register_mut=lambda r: [s.update(file=s["file"].upper()) for rec in r["decisions"]
                                              for s in rec["supporting_sources"]])
        self.assertFalse(tb.run(c).ok)

    # ---- the evidence manifest

    def test_editing_the_manifest_after_signing_is_rejected(self):
        c = self.chain()
        original = c.manifest.read_bytes()
        obj = json.loads(original)
        edits = {
            "hash changed": lambda o: o["files"][0].update(sha256=OTHER),
            "size changed": lambda o: o["files"][0].update(size=o["files"][0]["size"] + 1),
            "file added": lambda o: o["files"].append({"path": "zzz.txt", "sha256": SHA, "size": 1}),
            "file removed": lambda o: o["files"].pop(),
            "jurisdiction": lambda o: o.update(jurisdiction="Karnataka"),
        }
        for name, edit in edits.items():
            o = copy.deepcopy(obj)
            edit(o)
            c.manifest.write_bytes(em.canonical_bytes(o))
            with self.subTest(name):
                self.assertRejected(tb.run(c), "validity evidence manifest has changed since the registry bound it")
        c.manifest.write_bytes(original + b"\n")
        self.assertRejected(tb.run(c), "has changed since the registry bound it")

    def test_a_signed_but_non_canonical_manifest_is_rejected(self):
        c = self.chain(manifest_bytes_mut=lambda raw: json.dumps(json.loads(raw), indent=2).encode())
        self.assertRejected(tb.run(c), "not in canonical form")
        c = self.chain(manifest_bytes_mut=lambda raw: raw + b"\n")
        self.assertRejected(tb.run(c), "not in canonical form")

    def test_substituting_another_chains_manifest_is_rejected(self):
        c = self.chain()
        other = self.chain(manifest_mut=lambda o: o["files"].append({"path": "zz-extra.txt", "sha256": SHA, "size": 1}))
        self.assertNotEqual(c.manifest.read_bytes(), other.manifest.read_bytes())
        self.assertRejected(tb.run(c, evidence_manifest=other.manifest), "has changed since the registry bound it")

    def test_the_manifest_is_read_as_a_regular_file_with_a_size_limit(self):
        c = self.chain()
        with mock.patch.object(em, "MAX_MANIFEST_BYTES", 10):
            self.assertRejected(tb.run(c), "cannot read the evidence manifest")
        for p in (c.dir / "missing.json", c.dir):
            self.assertRejected(tb.run(c, evidence_manifest=p), "cannot read the evidence manifest")
        fifo = c.dir / "fifo"
        os.mkfifo(fifo)
        self.assertRejected(tb.run(c, evidence_manifest=fifo), "cannot read the evidence manifest")

    def test_a_cited_file_missing_from_the_signed_manifest_is_rejected(self):
        c = self.chain(manifest_mut=lambda o: o["files"].clear())
        self.assertRejected(tb.run(c), "not in the signed evidence manifest")

    def test_files_listed_but_not_cited_are_not_required(self):
        c = self.chain(manifest_mut=lambda o: o["files"].append({"path": "zz-unused.txt", "sha256": SHA, "size": 1}))
        self.assertTrue(tb.run(c).ok)

    # ---- evidence files

    def test_replacing_an_evidence_file_is_rejected_even_with_the_same_size(self):
        c = self.chain()
        target = c.evidence / sup.EV_FILE
        target.write_bytes(b"X" * len(sup.EV_BYTES))
        self.assertRejected(tb.run(c), "does not match the manifest SHA-256")

    def test_replacing_a_file_and_rewriting_its_hash_in_the_register_is_rejected(self):
        c = self.chain()
        new = b"Y" * len(sup.EV_BYTES)
        (c.evidence / sup.EV_FILE).write_bytes(new)
        reg = json.loads(c.register.read_text())
        for r in reg["decisions"]:
            for s in r["supporting_sources"]:
                if s["file"] == sup.EV_FILE:
                    s["sha256"] = sha_of(new)
        c.register.write_text(json.dumps(reg))
        self.assertRejected(tb.run(c), "has changed since the registry bound it")

    def test_replacing_a_file_and_rewriting_the_manifest_is_rejected(self):
        c = self.chain()
        new = b"Z" * len(sup.EV_BYTES)
        (c.evidence / sup.EV_FILE).write_bytes(new)
        obj = json.loads(c.manifest.read_bytes())
        for f in obj["files"]:
            if f["path"] == sup.EV_FILE:
                f["sha256"] = sha_of(new)
        c.manifest.write_bytes(em.canonical_bytes(obj))
        self.assertRejected(tb.run(c), "validity evidence manifest has changed since the registry bound it")

    def test_replacing_the_file_register_and_manifest_together_is_rejected(self):
        c = self.chain()
        new = b"W" * len(sup.EV_BYTES)
        (c.evidence / sup.EV_FILE).write_bytes(new)
        obj = json.loads(c.manifest.read_bytes())
        for f in obj["files"]:
            if f["path"] == sup.EV_FILE:
                f["sha256"] = sha_of(new)
        c.manifest.write_bytes(em.canonical_bytes(obj))
        reg = json.loads(c.register.read_text())
        for r in reg["decisions"]:
            for s in r["supporting_sources"]:
                if s["file"] == sup.EV_FILE:
                    s["sha256"] = sha_of(new)
        c.register.write_text(json.dumps(reg))
        a = tb.run(c)
        self.assertRejected(a, "has changed since the registry bound it")

    def test_a_whole_substitute_set_is_rejected_unless_the_registry_and_approval_are_resigned(self):
        c = self.chain()
        other = self.chain(tpv.one())
        for src, dst in ((other.register, c.register), (other.manifest, c.manifest)):
            dst.write_bytes(src.read_bytes())
        self.assertFalse(tb.run(c).ok)

    def test_links_below_the_evidence_directory_are_refused(self):
        c = self.chain()
        target = c.evidence / sup.EV_FILE
        data = target.read_bytes()
        kept = c.dir / "kept.txt"
        kept.write_bytes(data)                                                 # outside, same bytes
        target.unlink()
        target.symlink_to(kept)
        self.assertRejected(tb.run(c), "cannot be opened below the evidence directory")
        target.unlink()
        inside = c.evidence / "evidence" / "other.txt"
        inside.write_bytes(data)
        target.symlink_to(inside)                                              # inside, same bytes
        self.assertRejected(tb.run(c), "cannot be opened below the evidence directory")

    def test_a_linked_subdirectory_is_refused(self):
        c = self.chain()
        moved = c.dir / "moved"
        os.rename(c.evidence / "evidence", moved)
        (c.evidence / "evidence").symlink_to(moved)
        self.assertRejected(tb.run(c), "cannot be opened below the evidence directory")

    def test_a_fifo_in_place_of_evidence_is_rejected_without_blocking(self):
        c = self.chain()
        target = c.evidence / sup.EV_FILE
        target.unlink()
        os.mkfifo(target)
        self.assertFalse(tb.run(c).ok)

    def test_the_evidence_directory_itself_may_be_reached_through_a_link(self):
        c = self.chain()
        link = c.dir / "held-link"
        link.symlink_to(c.evidence)
        self.assertTrue(tb.run(c, evidence_dir=link).ok)

    def test_a_cited_path_that_escapes_is_rejected(self):
        for evil in ("../outside.txt", "/etc/hosts", "evidence/../../x", "a\\b"):
            def mut(r, evil=evil):
                r["decisions"][0]["supporting_sources"][0]["file"] = evil
            with self.subTest(evil=evil):
                a = tb.run(self.chain(register_mut=mut))
                self.assertFalse(a.ok)

    def test_a_missing_evidence_directory_is_rejected(self):
        c = self.chain()
        self.assertRejected(tb.run(c, evidence_dir=None), "cannot be verified")
        self.assertRejected(tb.run(c, evidence_dir=c.dir / "nowhere"), "evidence directory cannot be opened")

    def test_a_replacement_after_the_files_were_read_cannot_change_the_result(self):
        c = self.chain()
        register, manifest = c.register.read_bytes(), c.manifest.read_bytes()

        def swap():
            c.register.write_bytes(b"{}")
            c.manifest.write_bytes(b"{}")

        with tb.hook_after(gate.validity_decisions, "cited_files", swap):
            a = tb.run(c)
        self.assertTrue(a.ok, a.problems)
        self.assertEqual((a.register_sha256, a.manifest_sha256), (sha_of(register), sha_of(manifest)))

    def test_an_evidence_file_replaced_at_the_last_moment_is_rejected(self):
        c = self.chain()

        def swap():
            (c.evidence / sup.EV_FILE).write_bytes(b"Q" * len(sup.EV_BYTES))

        with tb.hook_after(gate.validity_decisions, "cited_files", swap):
            self.assertRejected(tb.run(c), "does not match the manifest SHA-256")

    # ---- jurisdiction

    def test_cross_jurisdiction_substitution_is_rejected(self):
        c = self.chain(register_mut=lambda r: r.update(jurisdiction="Karnataka"))
        self.assertRejected(tb.run(c), "decision register jurisdiction 'Karnataka' differs from the approval record's 'Telangana'")
        c = self.chain(manifest_mut=lambda o: o.update(jurisdiction="Karnataka"))
        self.assertRejected(tb.run(c), "evidence manifest jurisdiction 'Karnataka' differs")
        c = self.chain(register_mut=lambda r: r.pop("jurisdiction"))
        self.assertRejected(tb.run(c), "decision register jurisdiction None differs")
        c = self.chain(register_mut=lambda r: r.update(jurisdiction="telangana"))
        self.assertFalse(tb.run(c).ok)

    def test_a_register_from_another_jurisdiction_cannot_be_swapped_in_after_signing(self):
        c = self.chain()
        reg = json.loads(c.register.read_text())
        reg["jurisdiction"] = "Karnataka"
        c.register.write_text(json.dumps(reg))
        self.assertRejected(tb.run(c), "has changed since the registry bound it")

    # ---- the earlier links still hold

    def test_the_signature_chain_is_still_required(self):
        self.assertRejected(tb.run(self.chain(sign=False)), "not signed")
        self.assertRejected(tb.run(self.chain(listed=False)), "approval is not valid")
        self.assertRejected(tb.run(self.chain(key_status="revoked")), "approval is not valid")
        self.assertRejected(tb.run(self.chain(bound="2" * 64)), "changed since the registry bound it")
        self.assertRejected(tb.run(self.chain(binding=False)), "does not bind")

    def test_a_fixture_register_is_still_flagged_and_refused_by_default(self):
        self.assertRejected(tb.run(self.chain(fixture_register=True)), "synthetic fixture")
        a = tb.run(self.chain(fixture_register=True), allow_fixture=True)
        self.assertTrue(a.ok, a.problems)
        self.assertEqual((a.fixture, a.production), (True, False))


# ------------------------------------------------------------------------------------------------ Option A plausibility

def base():
    obj = led()
    ledger_obj, reg, files = sup.decorate(obj)
    return ledger_obj, reg, sup.held_table(files), pv.load_ledger(json.dumps(ledger_obj).encode())


def check(ledger, reg, held, **kw):
    return vd.check_decisions(ledger, reg, corpus_files=held, today=kw.pop("today", TODAY))


def text(problems):
    return " | ".join(f"{p.code} {p.subject}: {p.message}" for p in problems)


class PlausibilityTests(unittest.TestCase):
    def setUp(self):
        self.led_obj, self.reg, self.held, self.ledger = base()
        self.first = "LD-012"

    def rec(self, reg=None):
        return sup.register_record(reg or self.reg, self.first)

    def mutated(self, f):
        reg = copy.deepcopy(self.reg)
        f(self.rec(reg))
        return check(self.ledger, reg, self.held)

    def test_the_baseline_is_clean(self):
        self.assertEqual(check(self.ledger, self.reg, self.held), [])

    # pinned reviewer and preparer
    def test_an_approved_decision_must_be_pinned_by_reviewer_and_preparer_in_the_ledger(self):
        for field in ("reviewer", "prepared_by"):
            o = copy.deepcopy(self.led_obj)
            o["decisions"][0].pop(field)
            ledger = pv.load_ledger(json.dumps(o).encode())
            with self.subTest(field):
                self.assertIn("D15", {p.code for p in check(ledger, self.reg, self.held)})

    def test_a_decision_that_is_not_approved_is_not_required_to_be_pinned(self):
        o = copy.deepcopy(self.led_obj)
        reg = copy.deepcopy(self.reg)
        d = next(d for d in o["decisions"] if d["decision_id"] == "LD-013")
        d.update(status="pending", reviewer=None, prepared_by=None)
        rec = sup.register_record(reg, "LD-013")
        rec.update(status="pending", reviewer={"name": None, "designation": None, "organisation": None}, prepared_by=None)
        ledger = pv.load_ledger(json.dumps(o).encode())
        self.assertNotIn("D15", {p.code for p in check(ledger, reg, self.held)})

    # history
    def test_the_approving_history_entry_must_be_by_the_named_reviewer_on_the_review_date(self):
        self.assertIn("by the named reviewer", text(self.mutated(lambda r: r["history"][-1].update(by="nobody in particular"))))
        self.assertIn("by the named reviewer", text(self.mutated(lambda r: r["history"][-1].pop("by"))))
        self.assertIn("by the named reviewer", text(self.mutated(lambda r: r["history"][-1].update(by=None))))
        self.assertIn("must equal review_date", text(self.mutated(lambda r: r["history"][-1].update(date="2026-01-01"))))
        self.assertEqual(self.mutated(lambda r: r["history"][-1].update(by=f"  {sup.REVIEWER.upper()} ")), [])

    def test_history_dates_must_be_real_ordered_and_not_in_the_future(self):
        self.assertIn("earlier than the entry before", text(self.mutated(lambda r: r["history"][0].update(date="2026-06-01"))))
        self.assertIn("in the future", text(self.mutated(lambda r: r["history"][0].update(date="2999-01-01"))))
        for bad in ("2026-13-01", "01/02/2026", None, 5, ""):
            with self.subTest(bad=bad):
                self.assertIn("D6", {p.code for p in self.mutated(lambda r: r["history"][0].update(date=bad))})

    def test_a_history_entry_that_is_not_an_object_is_rejected(self):
        for bad in ("x", None, 5, []):
            with self.subTest(bad=bad):
                self.assertIn("D6", {p.code for p in self.mutated(lambda r: r["history"].insert(0, bad))})

    def test_the_single_entry_backdated_history_from_the_review_is_refused(self):
        def one(r):
            r["history"] = [{"date": "1999-01-01", "status": "approved", "by": "nobody in particular"}]
        self.assertTrue(self.mutated(one))                               # by != reviewer and date != review_date

    # machine names
    def test_machine_like_reviewer_text_beyond_the_old_list_is_refused(self):
        for name in ("Gemini", "Anthropic", "A.I. Reviewer", "Cl4ude", "Review Robot", "automation script", "language model",
                     "OpenAI", "Bot", "GPT-4", "Auto-generated", "ML Pipeline", "Claude", "assistant", "LLM"):
            for field in ("name", "designation", "organisation"):
                with self.subTest(name=name, field=field):
                    self.assertIn("D6", {p.code for p in self.mutated(lambda r: r["reviewer"].update({field: name}))})

    def test_ordinary_names_and_titles_are_not_refused_by_the_machine_filter(self):
        for name in ("Reviewer Gamma", "Alpha Chambers", "Senior Advocate", "Counsel to the State", "Reviewer Delta"):
            with self.subTest(name):
                self.assertNotIn("machine", text(self.mutated(lambda r: r["reviewer"].update(designation=name))))

    def test_synthetic_wording_is_refused_in_an_unflagged_register_but_not_in_a_flagged_one(self):
        for field, value in (("reviewer.name", "Synthetic Counsel"), ("reviewer.designation", "Fixture Advocate"),
                             ("reviewer.organisation", "Test Chambers"), ("prepared_by", "dummy preparer"),
                             ("decision", "approved (sample)"), ("rationale", "a throwaway rationale")):
            def put(r, field=field, value=value):
                if field.startswith("reviewer."):
                    r["reviewer"][field.split(".")[1]] = value
                else:
                    r[field] = value
            with self.subTest(field):
                reg = copy.deepcopy(self.reg)
                put(self.rec(reg))
                self.assertIn("synthetic or test wording", text(check(self.ledger, reg, self.held)))
                reg["fixture"] = True
                self.assertNotIn("synthetic or test wording", text(check(self.ledger, reg, self.held)))

    # honest limit
    def test_a_plausible_invented_reviewer_is_NOT_detected_and_this_is_documented(self):
        """The checks are filters, not authentication. A made-up human-looking name passes them; only the signed binding (the
        approval authority attesting the exact register) stands between that and acceptance."""
        o = copy.deepcopy(self.led_obj)
        o["decisions"][0]["reviewer"] = {"name": "Reviewer Gamma"} if isinstance(o["decisions"][0]["reviewer"], dict) else "Reviewer Gamma"
        reg = copy.deepcopy(self.reg)
        r = self.rec(reg)
        r["reviewer"]["name"] = "Reviewer Gamma"
        r["history"][-1]["by"] = "Reviewer Gamma"
        ledger = pv.load_ledger(json.dumps(o).encode())
        self.assertEqual(check(ledger, reg, self.held), [])


class NoReviewerAuthenticationClaimTests(unittest.TestCase):
    """Option B (reviewer keys) is not built, and nothing may claim that a reviewer was cryptographically verified."""

    NEW = ("validity_decisions.py", "evidence_manifest.py", "ledger_acceptance.py")

    def test_no_reviewer_key_or_signature_mechanism_exists_in_the_new_code(self):
        for name in self.NEW:
            src = (ROOT / "backend" / name).read_text(encoding="utf-8")
            code = re.sub(r'""".*?"""', "", src, flags=re.S)
            with self.subTest(name):
                for forbidden in ("reviewer_key", "reviewer-keys", "reviewer_signature", "verify_signature", "Ed25519", "cryptography"):
                    self.assertNotIn(forbidden, code)

    def test_the_new_code_states_the_limit(self):
        for name in self.NEW:
            src = (ROOT / "backend" / name).read_text(encoding="utf-8")
            with self.subTest(name):
                self.assertIn("does NOT authenticate", src, name)
        gate_src = (ROOT / "backend" / "ledger_acceptance.py").read_text(encoding="utf-8")
        self.assertIn("never claims that a reviewer's identity or personal approval was cryptographically verified", gate_src)

    def test_the_trust_model_documents_the_attestation_limit(self):
        doc = (ROOT / "docs" / "approval-trust-model.md").read_text(encoding="utf-8")
        for needle in ("attest", "not authenticate", "no reviewer key"):
            self.assertIn(needle, doc.lower())

    def test_acceptance_never_reports_a_verified_reviewer(self):
        fields = {f for f in gate.Acceptance.__dataclass_fields__}
        self.assertFalse({f for f in fields if "reviewer" in f or "verified" in f})


class IsolationTests(unittest.TestCase):
    def test_no_runtime_module_imports_the_new_module(self):
        for p in sorted((ROOT / "backend").glob("*.py")):
            if p.name in ("evidence_manifest.py", "ledger_acceptance.py", "validity_decisions.py", "provision_validity.py"):
                continue
            t = p.read_text(encoding="utf-8", errors="replace")
            with self.subTest(p.name):
                self.assertIsNone(re.search(r"from backend import[^\n]*\bevidence_manifest\b|from backend\.evidence_manifest|"
                                            r"import backend\.evidence_manifest|import evidence_manifest", t))

    def test_the_real_decision_register_and_registry_match_their_pinned_hashes(self):
        self.assertEqual(REAL_REGISTRY_SHA256, REAL_REGISTRY_SHA_BEFORE)
        self.assertEqual(REAL_REGISTER_SHA256, REAL_REGISTER_SHA_BEFORE)

    def test_the_real_decision_register_and_registry_are_untouched(self):
        self.assertEqual(sha_of(sup.REAL_REGISTER.read_bytes()), REAL_REGISTER_SHA256)
        self.assertEqual(sha_of((ROOT / "legal-status" / "source-status.json").read_bytes()), REAL_REGISTRY_SHA256)

    def test_the_new_module_only_reads_files_and_never_writes(self):
        src = (ROOT / "backend" / "evidence_manifest.py").read_text(encoding="utf-8")
        for forbidden in ("write(", "write_bytes", "write_text", "os.rename", "os.replace", "os.remove", "os.unlink", "O_WRONLY", "O_RDWR",
                          "O_CREAT", "shutil"):
            self.assertNotIn(forbidden, src)


if __name__ == "__main__":
    unittest.main()
