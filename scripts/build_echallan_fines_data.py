"""Build backend/echallan_fines_data.json from the scraped files in research/ (read-only inputs, never modified).

Usage: python3 scripts/build_echallan_fines_data.py [--page-hash mv-act-rules=<sha256> --page-hash mvact=<sha256>]

The output keeps every scraped row exactly as printed (offence, section, amount text) and adds only: an id, the page it came
from, the section numbers that belong to the Motor Vehicles Act (for search), the cross-table pairing found by the audit, and the
provenance (file hashes). It states no legal status: the figures are what the Telangana Police website displays."""
import argparse, hashlib, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "research" / "echallan-fines-unverified.json"
AUDIT = ROOT / "research" / "echallan-fines-audit.json"
AUDIT_MD = ROOT / "research" / "echallan-fines-audit.md"
OUT = ROOT / "backend" / "echallan_fines_data.json"

TABLES = {
    "mv-act-rules": {"prefix": "W", "label": "MV Act Offences - Wheel-wise Maximum Penalty (wheel-wise table)",
                     "url": "https://echallan.tspolice.gov.in/htp/mv-act-rules.html"},
    "mvact": {"prefix": "P", "label": "Motor Vehicles Act & Traffic Rules (plain table)",
              "url": "https://echallan.tspolice.gov.in/htp/mvact.html"},
}
NON_ACT = re.compile(r"CMVR|TSMVR|APMVR|TS MVR|MVDR|RRR|\bCR\b|CP Act|C\.P\.|IPC|Rules|\bR\.? ?\d|MVR|Hyderabad City|TSMV", re.I)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def act_sections(section):
    out = []
    for seg in re.split(r"[/,]", section):
        if NON_ACT.search(seg):
            continue
        out += re.findall(r"\b(\d{2,3})\b", seg)
    return sorted(set(out), key=int)


def rows_hash(entries):
    canon = json.dumps([[e["id"], e["offence"], e["section"], e["amount_displayed"]] for e in entries], ensure_ascii=False)
    return hashlib.sha256(canon.encode()).hexdigest()


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--page-hash", action="append", default=[])
    args = ap.parse_args(argv)
    page_hash = dict(p.split("=", 1) for p in args.page_hash)
    src = json.loads(SRC.read_text())
    audit = json.loads(AUDIT.read_text())
    pair = {e["id"]: e["cross_table"] for e in audit["entries"]}
    cls = {e["id"]: e["classification"] for e in audit["entries"]}
    entries = []
    for key, meta in TABLES.items():
        for i, (offence, section, amount) in enumerate(src["rows"][key]):
            eid = f"{meta['prefix']}{i:03d}"
            entries.append({"id": eid, "table": key, "offence": offence, "section": section, "amount_displayed": amount,
                            "act_sections": act_sections(section), "audit_class": cls[eid],
                            "other_table_pairs": [{"status": c["status"], "other": c["other"]} for c in pair.get(eid, [])]})
    assert len(entries) == 162, len(entries)
    data = {
        "kind": "secondary_source_website_amounts",
        "amount_label": "Amount displayed on the Telangana Police e-Challan website.",
        "disclaimer": ("These are indicative figures published on the Telangana Police website and may be subject to amendments. "
                       "Please check the official e-Challan portal for the latest amount."),
        "status": "Not independently verified. Not a statutory fine and not a Telangana compounding amount.",
        "provenance": {
            "retrieved": src["fetched"],
            "tables": {k: {"url": v["url"], "label": v["label"], "page_sha256": page_hash.get(k), "entries": len(src["rows"][k])}
                       for k, v in TABLES.items()},
            "scraped_file": "research/echallan-fines-unverified.json", "scraped_file_sha256": sha(SRC),
            "audit_json": "research/echallan-fines-audit.json", "audit_json_sha256": sha(AUDIT),
            "audit_md": "research/echallan-fines-audit.md", "audit_md_sha256": sha(AUDIT_MD),
            "rows_sha256": rows_hash(entries), "entry_count": len(entries)},
        "entries": entries}
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    print("wrote", OUT, len(entries), data["provenance"]["rows_sha256"])


if __name__ == "__main__":
    main(sys.argv[1:])
