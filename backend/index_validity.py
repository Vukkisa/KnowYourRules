"""Validity-date checks for chunk metadata and for an index compared with the source manifest. Pure functions, no I/O.

A chunk is versioned when it carries integer valid_from and valid_to (yyyymmdd, inclusive, 99991231 = open end). Chroma
cannot store None, so unknown validity is encoded as both keys absent plus validity_status = "unknown". Nothing here
infers a date: it only checks that what the index holds is what the reviewed manifest says.
"""

from __future__ import annotations

from collections import Counter

from backend import tg_manifest as tm


def chunk_problems(m: dict) -> list[str]:
    """Why one chunk's validity metadata is unusable ([] when it is consistent or plainly unversioned)."""
    start, end, status = m.get("valid_from"), m.get("valid_to"), m.get("validity_status")
    if status is None and start is None and end is None:
        return []  # legacy chunk from before the validity fields: unversioned, never temporal evidence
    if status is None:
        return ["validity dates without a validity_status"]
    if (start is None) != (end is None):
        return ["only one of valid_from and valid_to is set"]
    return [p.split(": ", 1)[-1] if ": " in p else p
            for p in tm.validity_problems(start, end, status, "verified", "chunk")]


def _expected(entry) -> dict:
    return tm.validity_metadata(entry)


def _actual(m: dict) -> dict:
    return {k: m[k] for k in ("validity_status", "valid_from", "valid_to") if k in m}


def report(metadatas, entries=None) -> dict:
    """Counts and problems for an index's chunk metadata, compared with the manifest entries when given.
    problems:   inconsistencies that must stop a build (a malformed range, a chunk that disagrees with its manifest entry,
                a manifest document with no chunks, a chunk from a document outside the manifest)
    unflagged:  chunks with no validity_status at all (built before the fields existed)
    unknown:    manifest ids whose validity is not verified (flagged; their chunks stay unversioned)
    """
    metadatas = [m or {} for m in metadatas]
    problems, per = [], {}
    by_sha = {e.sha256: e for e in entries or []}
    for m in metadatas:
        sha = m.get("sha256", "")
        row = per.setdefault(m.get("manifest_id") or sha[:12], {"chunks": 0, "versioned": 0, "unversioned": 0,
                                                                   "status": set(), "mismatched": 0})
        row["chunks"] += 1
        row["status"].add(m.get("validity_status", "(none)"))
        has = isinstance(m.get("valid_from"), int) and isinstance(m.get("valid_to"), int)
        row["versioned" if has else "unversioned"] += 1
        bad = chunk_problems(m)
        if bad:
            problems.append(f"{m.get('manifest_id') or sha[:12]} {m.get('provision_id', '?')}: " + "; ".join(bad))
            row["mismatched"] += 1
        elif entries is not None:
            entry = by_sha.get(sha)
            if entry is None:
                problems.append(f"{m.get('manifest_id') or sha[:12]}: chunk from a document outside the manifest")
                row["mismatched"] += 1
            elif _actual(m) != _expected(entry) and not (not _actual(m) and _expected(entry) == {"validity_status": tm.UNKNOWN}):
                problems.append(f"{entry.id} {m.get('provision_id', '?')}: chunk validity {_actual(m) or 'absent'} "
                                f"differs from the manifest {_expected(entry)}")
                row["mismatched"] += 1
    if entries is not None:
        present = {m.get("sha256") for m in metadatas}
        problems += [f"{e.id}: no chunks in the index" for e in entries if e.sha256 not in present and e.source_class != "draft"]
    flat = Counter()
    for row in per.values():
        flat["chunks"] += row["chunks"]
        flat["versioned"] += row["versioned"]
        flat["unversioned"] += row["unversioned"]
    return {
        "chunks": flat["chunks"], "versioned": flat["versioned"], "unversioned": flat["unversioned"],
        "unflagged": sum(1 for m in metadatas if "validity_status" not in m),
        "unknown": sorted(tm.unverified_validity(entries)) if entries is not None else [],
        "sources": {k: dict(v, status=sorted(v["status"])) for k, v in sorted(per.items())},
        "problems": problems,
    }
