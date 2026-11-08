"""
Offline signing tool for the approval authority. NOT used by the server.

Signs the exact bytes of an approval record with the authority's Ed25519 private key and writes
<record>.sig. The private key must be a PEM file held by the authority OUTSIDE this repository; the
tool refuses a key stored inside it. See docs/approval-trust-model.md.

    python scripts/sign_approval_record.py RECORD.json --key /secure/path/authority.pem --key-id KEY_ID
    python scripts/sign_approval_record.py --public-key --key /secure/path/authority.pem
"""

import argparse
import base64
import json
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

REPO_ROOT = Path(__file__).resolve().parent.parent


class SigningError(Exception):
    pass


def load_private_key(key_path, repo_root=REPO_ROOT, password=None) -> Ed25519PrivateKey:
    key_path = Path(key_path).resolve()
    if key_path == repo_root or repo_root in key_path.parents:
        raise SigningError("refusing a private key stored inside the repository")
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=password)
    if not isinstance(key, Ed25519PrivateKey):
        raise SigningError("the key must be an Ed25519 private key")
    return key


def signature_document(record_bytes: bytes, key: Ed25519PrivateKey, key_id: str) -> dict:
    return {"schema_version": 1, "algorithm": "ed25519", "key_id": key_id,
            "signature": base64.b64encode(key.sign(record_bytes)).decode("ascii")}


def public_key_b64(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode("ascii")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("record", nargs="?")
    ap.add_argument("--key", required=True, help="authority's Ed25519 private key (PEM), outside the repository")
    ap.add_argument("--key-id")
    ap.add_argument("--public-key", action="store_true", help="print the base64 public key for the trusted-keys file")
    args = ap.parse_args(argv)
    try:
        key = load_private_key(args.key)
        if args.public_key:
            print(public_key_b64(key))
            return 0
        if not args.record or not args.key_id:
            raise SigningError("RECORD and --key-id are required to sign")
        record = Path(args.record)
        sig = signature_document(record.read_bytes(), key, args.key_id)
        Path(str(record) + ".sig").write_text(json.dumps(sig, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {record}.sig (key_id {args.key_id})")
        return 0
    except (SigningError, OSError, ValueError) as e:
        print(f"Signing failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
