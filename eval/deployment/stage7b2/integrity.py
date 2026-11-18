"""Stage 7B.2: read-only integrity record of the real index and lifecycle registry. Prints digests and checks them against the digests
recorded in Stages 6D/7A/7B/7B.1. Opens nothing for writing. usage: python3 eval/deployment/stage7b2/integrity.py"""
import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from backend import document_lifecycle as dl  # noqa: E402

INDEX_DIGEST = "140cd2008980f7e64858a8089d81f0346f758db1eda4d8c5c390418eac0ebe29"
REGISTRY_DIGEST = "5f4094d88cf9b770b7210749fdadddfeea4d4c0cfd168c39bb3b905767bbdbe3"


def main():
    idx, reg = dl.tree_digest(ROOT / "chroma_telangana_preview_s11"), dl.tree_digest(ROOT / "legal" / "lifecycle")
    print(f"real index tree digest:      {idx}\n{'INDEX UNCHANGED' if idx == INDEX_DIGEST else 'INDEX CHANGED'}")
    print(f"real lifecycle tree digest:  {reg}\n{'REGISTRY UNCHANGED' if reg == REGISTRY_DIGEST else 'REGISTRY CHANGED'}")
    for rel in ("legal/lifecycle/registry.json", "legal/lifecycle/audit.jsonl"):
        print(hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() + "  " + rel)
    for cmd in ("verify", "audit-verify"):
        out = subprocess.run([sys.executable, "-m", "backend.document_lifecycle", "--state-dir", "legal/lifecycle", cmd], cwd=ROOT, capture_output=True, text=True)
        print(f"lifecycle {cmd}: {out.stdout.strip() or out.stderr.strip()}")
    return 0 if (idx, reg) == (INDEX_DIGEST, REGISTRY_DIGEST) else 1


if __name__ == "__main__":
    raise SystemExit(main())
