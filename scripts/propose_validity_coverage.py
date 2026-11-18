#!/usr/bin/env python3
"""Propose provision-validity coverage (Step 5). DEVELOPMENT TOOL, read-only on every input.

    python scripts/propose_validity_coverage.py --manifest M.json --corpus DIR [--index-dir CHROMA_DIR] \
        [--registry legal-status/source-status.json] --out dev-output/validity-coverage/NAME [--overwrite]

Reads the manifest, the held source files and (optionally) one Chroma directory's SQLite file in read-only immutable mode, and writes
`coverage-report.json` and `coverage-report.md` under dev-output/. It approves nothing, writes no ledger, approval, register,
manifest or registry, never opens a Chroma client, and refuses any output location outside dev-output/.
Exit 0 = the report was written (it can still list problems). Exit 2 = refused or unreadable input.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import source_status, tg_manifest, validity_coverage as vc  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--index-dir")
    ap.add_argument("--registry")
    ap.add_argument("--out", required=True)
    ap.add_argument("--overwrite", action="store_true")
    a = ap.parse_args(argv)
    inputs = [a.manifest, a.corpus] + ([a.index_dir] if a.index_dir else []) + ([a.registry] if a.registry else [])
    try:
        out = vc.check_output_dir(a.out, ROOT, protected=inputs)       # refuse before reading anything
    except vc.OutputRefused as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    try:
        source = vc.read_source_chunks(a.manifest, a.corpus)
    except (tg_manifest.ManifestError, OSError) as e:
        print(f"cannot read the manifest or corpus: {e.__class__.__name__}", file=sys.stderr)
        return 2
    index, index_error = None, None
    if a.index_dir:
        try:
            index = vc.read_index_chunks(a.index_dir)
        except vc.ReadError as e:
            index_error = str(e)
    registry = None
    if a.registry:
        registry = source_status.load(a.registry)
        registry = registry if registry.valid else None
    report = vc.analyze(source, index, registry=registry, index_error=index_error)
    try:
        written = vc.write_report(report, out, ROOT, protected=inputs, overwrite=a.overwrite)
    except vc.OutputRefused as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    c, p = report["chunk_counts"], report["provisions"]
    print(f"documents={report['inputs']['documents']} source_chunks={report['inputs']['source_chunks']} "
          f"index_chunks={report['inputs']['index_chunks']} verified={c['verified']} candidate={c['candidate']} "
          f"ambiguous={c['ambiguous']} unmapped={c['unmapped']} provisions_without_indexed_chunks={p['without_indexed_chunks']}")
    for w in written:
        print("wrote", w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
