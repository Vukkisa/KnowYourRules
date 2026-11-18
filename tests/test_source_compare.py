"""backend/source_compare.py: checksum verification, text normalisation and the chunk-vs-official comparison.
Synthetic files only; no corpus, index or network is touched."""

import ast
import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from backend import source_compare as sc


def _write(root: Path, rel: str, data: bytes) -> str:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


class ChecksumTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_ok_mismatch_missing(self):
        h_ok = _write(self.root, "goir/a.pdf", b"A")
        _write(self.root, "html/b.htm", b"B-changed")
        (self.root / "SHA256SUMS").write_text(
            f"{h_ok}  ./goir/a.pdf\n{hashlib.sha256(b'B').hexdigest()}  ./html/b.htm\n"
            f"{hashlib.sha256(b'C').hexdigest()}  ./gone.pdf\n\n")
        r = sc.verify_checksums(self.root)
        self.assertEqual(r, {"ok": ["goir/a.pdf"], "mismatch": ["html/b.htm"], "missing": ["gone.pdf"]})

    def test_cli_exit_code_reflects_failures(self):
        _write(self.root, "a.htm", b"x")
        (self.root / "SHA256SUMS").write_text(f"{'0' * 64}  ./a.htm\n")
        with mock.patch("sys.stdout"):
            self.assertEqual(sc.main(["--sources", str(self.root), "checksums"]), 1)
        (self.root / "SHA256SUMS").write_text(f"{hashlib.sha256(b'x').hexdigest()}  ./a.htm\n")
        with mock.patch("sys.stdout"):
            self.assertEqual(sc.main(["--sources", str(self.root), "checksums"]), 0)


class CompareTests(unittest.TestCase):
    OFFICIAL = "437. Crash helmets to be worn :- The protective headgear under Section 129 shall be a standard one."

    def test_norm_quotes_dashes_nbsp_case(self):
        self.assertEqual(sc.norm("“A”–B\xa0’c’  D"), "\"a\"-b 'c' d")

    def test_verbatim(self):
        r = sc.compare("437. Crash helmets  to be\nworn :- The protective", self.OFFICIAL)
        self.assertTrue(r["verbatim"])
        self.assertIsNone(r["divergence"])

    def test_whitespace_only_difference(self):
        r = sc.compare("437. Crash helmets to be worn : - The protective headgear", self.OFFICIAL)
        self.assertFalse(r["verbatim"])
        self.assertTrue(r["ignoring_whitespace"])
        self.assertTrue(r["ignoring_whitespace_and_pipes"])

    def test_pipe_separators_reported_separately(self):
        r = sc.compare("The protective | headgear | under Section 129", self.OFFICIAL)
        self.assertFalse(r["verbatim"])
        self.assertFalse(r["ignoring_whitespace"])
        self.assertTrue(r["ignoring_whitespace_and_pipes"])

    def test_real_divergence_fails_every_level(self):
        body = "437. Crash helmets to be worn :- The protective headgear need not be a standard one."
        r = sc.compare(body, self.OFFICIAL)
        self.assertFalse(r["verbatim"] or r["ignoring_whitespace"] or r["ignoring_whitespace_and_pipes"])
        self.assertEqual(sc.norm(body)[:r["matched_prefix"]], sc.norm(self.OFFICIAL)[:r["matched_prefix"]])
        self.assertIn("need not", r["divergence"])

    def test_html_text_skips_script_and_style(self):
        t = sc.html_text(b"<html><style>x{}</style><script>var a=1</script><p>186 (1) Text</p></html>")
        self.assertIn("186 (1) Text", t)
        self.assertNotIn("var a", t)

    def test_pdf_text_uses_local_binary_only(self):
        with mock.patch("subprocess.run") as run:
            run.return_value.stdout = "ORDER"
            self.assertEqual(sc.pdf_text("x.pdf"), "ORDER")
        self.assertEqual(run.call_args.args[0][:2], ["pdftotext", "-layout"])


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "chroma.sqlite3"
        con = sqlite3.connect(self.db)
        con.execute("create table embedding_metadata (id, key, string_value, int_value, float_value, bool_value)")
        meta = {"manifest_id": "tmvr-1989-chap-8", "provision_id": "Rule 437", "location": "html/c8.htm#42",
                "chroma:document": "TMVR - Rule 437 - header\n437. Crash helmets to be worn :- standard one."}
        for k, v in meta.items():
            con.execute("insert into embedding_metadata values (1, ?, ?, null, null, null)", (k, v))
        for k, v in {"part": 1, "parts": 1, "answer_eligible": 1}.items():
            con.execute("insert into embedding_metadata values (1, ?, null, ?, null, null)", (k, v))
        con.commit()
        con.close()
        _write(self.root, "html/c8.htm", b"<p>437. Crash helmets to be worn :- standard one.</p>")

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_chunks_and_compares_with_source(self):
        chunks = sc.index_chunks(self.db)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(sc.chunk_body(chunks[0]), "437. Crash helmets to be worn :- standard one.")
        [r] = sc.compare_provision(chunks, self.root, "tmvr-1989-chap-8", "Rule 437")
        self.assertTrue(r["verbatim"])
        self.assertEqual(r["part"], "1/1")
        self.assertEqual(sc.compare_provision(chunks, self.root, "tmvr-1989-chap-8", "Rule 186"), [])

    def test_index_is_opened_read_only(self):
        before = self.db.read_bytes()
        with mock.patch.object(sc.sqlite3, "connect", wraps=sqlite3.connect) as conn:
            sc.index_chunks(self.db)
        self.assertIn("mode=ro", conn.call_args.args[0])
        self.assertEqual(self.db.read_bytes(), before)

    def test_source_rel_from_location(self):
        self.assertEqual(sc.source_rel({"location": "goir/x.pdf#page=1 .. goir/x.pdf#page=3"}), "goir/x.pdf")
        self.assertEqual(sc.source_rel({"location": "html-snapshots/t/m.htm#58"}), "html-snapshots/t/m.htm")


class SafetyTests(unittest.TestCase):
    def test_no_network_or_model_imports(self):
        tree = ast.parse(Path(sc.__file__).read_text())
        names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                 for a in (n.names if isinstance(n, ast.Import) else [ast.alias(n.module or "")])}
        self.assertFalse(names & {"socket", "http", "urllib", "requests", "httpx", "groq", "chromadb", "openai"})
        self.assertNotIn("API_KEY", Path(sc.__file__).read_text())


if __name__ == "__main__":
    unittest.main()
