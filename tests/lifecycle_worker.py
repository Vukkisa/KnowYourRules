"""Subprocess helper for tests/test_lifecycle_hardening.py: one lifecycle operation in its own process, with the fake embedder
and chunker of test_document_lifecycle (no Ollama, no model download). argv[1] is a JSON spec. Prints one JSON line:
{"ok": true, "result": ...} or {"ok": false, "error_type": ..., "error": ...}. Special ops: hold_lock (keeps the lifecycle lock
for spec["hold"] seconds after printing LOCKED), slow_swap (approve whose index swap sleeps, printing IN_SWAP first)."""
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import test_document_lifecycle as tdl  # noqa: E402

from backend import document_lifecycle as dl  # noqa: E402
from backend import tg_manifest  # noqa: E402


def entry(spec):
    path = Path(spec["corpus"]) / spec["file"]
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    return tg_manifest.ManifestEntry(
        id=spec["source"], title="Fixture Rules", document_type="Rules", issuing_authority=None, document_number=None,
        publication_date=None, effective_date=None, source_url=None, file=spec["file"], jurisdiction="Telangana",
        format="html", source_class="unverified_snapshot", verification_status="unverified", sha256=sha, notes=None)


def main():
    spec = json.loads(sys.argv[1])
    lc = dl.Lifecycle(spec["state"], spec["db"], embeddings=tdl.FakeEmbedder(), chunker=tdl.fake_chunker,
                      lock_timeout=spec.get("timeout", 30.0))
    by = spec.get("by", "worker")
    try:
        op = spec["op"]
        if op == "ingest_approve":
            r = lc.ingest(entry(spec), spec["corpus"], by=by)
            res = lc.approve(spec["source"], r["version"], by=by) if r["outcome"] != "unchanged" else r
        elif op == "approve":
            res = lc.approve(spec["source"], spec["version"], by=by)
        elif op == "withdraw":
            res = lc.withdraw(spec["source"], spec["version"], by=by)
        elif op == "recover":
            res = lc.recover(by)
        elif op == "hold_lock":
            with lc._mutation("hold_lock", by):
                print("LOCKED", flush=True)
                time.sleep(spec["hold"])
            res = "released"
        elif op == "slow_swap":
            orig = lc._swap

            def slow(*a, **k):
                print("IN_SWAP", flush=True)
                time.sleep(spec["hold"])
                return orig(*a, **k)
            lc._swap = slow
            res = lc.approve(spec["source"], spec["version"], by=by)
        else:
            raise SystemExit(f"unknown op {op}")
        print(json.dumps({"ok": True, "result": res}, default=str), flush=True)
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"ok": False, "error_type": type(e).__name__, "error": str(e)[:400]}), flush=True)


if __name__ == "__main__":
    main()
