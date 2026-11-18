"""Test-only helpers for lifecycle bootstrap. BASIS is a synthetic approval basis (a recorded statement, not a credential);
status_file_for writes a source-status registry naming only some documents, which is how a test limits what bootstrap approves.
Nothing here approves anything real."""
import json
from pathlib import Path

BASIS = "synthetic approval basis for tests: a recorded statement, not a credential"


def status_file_for(dir_, metadatas, only=None):
    """A source-status registry listing the distinct documents of some chunk metadata (all, or only the given hashes)."""
    dir_ = Path(dir_)
    dir_.mkdir(parents=True, exist_ok=True)
    seen, entries = set(), []
    for m in metadatas:
        sha = m["sha256"]
        if sha in seen or (only is not None and sha not in only):
            continue
        seen.add(sha)
        entries.append({"manifest_id": m["manifest_id"], "file": m["source_file"], "sha256": sha, "status": "unverified_snapshot"})
    path = dir_ / "source-status.json"
    path.write_text(json.dumps({"schema_version": 1, "entries": entries}))
    return path
