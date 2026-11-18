"""Real integration test for "View source": the real backend, a real Chroma index and real Ollama embeddings.

Needs data and a service the offline suite does not have, so it is skipped unless both are present:
    KYR_REAL_INDEX_DIR=/path/to/a/telangana/index  python3 -m unittest discover -s tests -p "test_view_source_real.py"
with Ollama serving nomic-embed-text on 127.0.0.1:11434. Set KYR_REQUIRE_REAL_BACKEND=1 to fail instead of skip.
The index is copied to a temporary directory first; the directory you name is never opened.
RAG_VECTOR_SEARCH (exact or hnsw) is passed through. See tests/real_backend_probe.py for what is not real.
"""

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX_DIR = os.environ.get("KYR_REAL_INDEX_DIR", "")
REQUIRED = os.environ.get("KYR_REQUIRE_REAL_BACKEND", "").strip().lower() in ("1", "true", "yes")


def ollama_up() -> bool:
    try:
        socket.create_connection(("127.0.0.1", 11434), timeout=1).close()
        return True
    except OSError:
        return False


def missing() -> str | None:
    if not INDEX_DIR or not Path(INDEX_DIR).is_dir():
        return "KYR_REAL_INDEX_DIR is not set to an index directory"
    if not ollama_up():
        return "Ollama is not running on 127.0.0.1:11434"
    return None


class RealViewSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reason = missing()
        if reason and REQUIRED:
            raise AssertionError(f"real backend test required but cannot run: {reason}")
        if reason:
            raise unittest.SkipTest(reason)
        cls.tmp = tempfile.mkdtemp(prefix="kyr-real-index-")
        cls.addClassCleanup(shutil.rmtree, cls.tmp, ignore_errors=True)
        copy = Path(cls.tmp) / "index"
        shutil.copytree(INDEX_DIR, copy)
        # Only safe settings are passed on: no answer-mode switch, no key, no approval file can leak in.
        env = {k: v for k, v in os.environ.items() if not k.startswith(("TG_", "GROQ_", "GEMINI_", "PROVIDER_"))}
        env["TG_DB_DIR"] = str(copy)
        run = subprocess.run([sys.executable, str(ROOT / "tests" / "real_backend_probe.py")], cwd=ROOT, env=env,
                             capture_output=True, text=True, timeout=600)
        if run.returncode != 0:
            raise AssertionError("probe failed:\n" + run.stderr[-3000:])
        cls.out = json.loads(run.stdout.strip().splitlines()[-1])
        cls.stored = {(sha, pid, text): label for sha, pid, text, label in cls.out["stored"]}

    def passages(self, answer):
        return [(s, p) for s in answer["body"]["sources"] for p in s["passages"]]

    def assert_passages_are_stored_chunks(self, answer):
        for s, p in self.passages(answer):
            key = (p["sha256"], p["provision_id"], p["text"])
            self.assertIn(key, self.stored, f"{p['label']} is not the text of a stored chunk")
            self.assertEqual(p["label"], self.stored[key])

    def test_index_is_loaded_in_the_mode_under_test(self):
        self.assertEqual(self.out["status"]["index"], "ready")
        self.assertGreater(self.out["status"]["chunks"], 0)
        self.assertEqual(self.out["vector_search"], os.environ.get("RAG_VECTOR_SEARCH", "exact").strip().lower())

    def test_project_configuration_as_it_is_returns_no_answer_and_no_sources(self):
        self.assertEqual(self.out["status"]["answer_mode"], "disabled")
        self.assertFalse(self.out["status"]["kb_approved"])
        for a in self.out["as_is"]:
            self.assertEqual((a["status"], a["body"]["kind"], a["body"]["sources"]), (200, "unavailable", []))
            self.assertTrue(a["retrieved"])  # retrieval itself works; only answering is switched off

    def test_grounded_answers_list_exactly_the_cited_chunks(self):
        answers = [a for a in self.out["grounded"] if a["body"]["kind"] == "answer"]
        self.assertGreaterEqual(len(answers), 3, [a["body"]["kind"] for a in self.out["grounded"]])
        for a in answers:
            passages = self.passages(a)
            retrieved = {tuple(k) for k in a["retrieved"]}
            cited_lines = set(re.findall(r"^\[(\d+)\] ", a["body"]["response"], re.M))
            self.assertEqual(len(passages), len(cited_lines), a["question"])
            self.assertTrue(all(p["cited"] for _, p in passages))
            self.assertLess(len(passages), len(retrieved), "an uncited retrieved chunk must not be listed")
            for s, p in passages:
                self.assertIn((p["sha256"], p["provision_id"], p["text"]), retrieved)
            self.assert_passages_are_stored_chunks(a)

    def test_grounded_answers_cover_several_documents_and_several_passages_of_one(self):
        answers = [a for a in self.out["grounded"] if a["body"]["kind"] == "answer"]
        self.assertTrue(any(len(a["body"]["sources"]) > 1 for a in answers), "no answer cited two documents")
        self.assertTrue(any(len(s["passages"]) > 1 for a in answers for s in a["body"]["sources"]),
                        "no answer cited two passages of one document")

    def test_development_output_lists_every_retrieved_chunk_and_marks_none_cited(self):
        for a in self.out["development"]:
            self.assertEqual(a["body"]["kind"], "development")
            passages = self.passages(a)
            self.assertEqual({(p["sha256"], p["provision_id"], p["text"]) for s, p in passages},
                             {tuple(k) for k in a["retrieved"]})
            self.assertFalse(any(p["cited"] for _, p in passages))
            self.assert_passages_are_stored_chunks(a)

    def test_each_document_is_listed_once_and_passages_keep_their_own_file(self):
        answers = self.out["grounded"] + self.out["development"]
        rows = [s for a in answers for s in a["body"]["sources"]]
        self.assertTrue(rows)
        for a in answers:
            ids = [s["document_id"] for s in a["body"]["sources"]]
            self.assertEqual(len(ids), len(set(ids)), f"a document is listed twice: {a['question']}")
        for s in rows:
            files = {(f["file"], f["sha256"], f["manifest_id"]) for f in s["files"]}
            self.assertEqual((s["file"], s["sha256"]), (s["files"][0]["file"], s["files"][0]["sha256"]))
            for p in s["passages"]:
                self.assertIn((p["file"], p["sha256"], p["manifest_id"]), files)
                self.assertTrue(p["chunk_id"].startswith(p["manifest_id"] + "::"))
            if len(s["files"]) > 1:  # only chapter files of one instrument share a row
                self.assertTrue(all(f["manifest_id"].startswith(s["document_id"] + "-chap-") for f in s["files"]))
            else:
                self.assertIn(s["document_id"], (s["files"][0]["manifest_id"],
                                                 s["files"][0]["manifest_id"].rsplit("-chap-", 1)[0]))
            if s["document_id"].startswith("go-"):  # a government order is never folded into the Rules
                self.assertEqual([f["manifest_id"] for f in s["files"]], [s["document_id"]])
        self.assertTrue(any(len(s["files"]) > 1 for s in rows), "no answer drew on two chapter files of the Rules")

    def test_passage_text_is_the_stored_text_without_its_header_line(self):
        for a in self.out["grounded"] + self.out["development"]:
            for s, p in self.passages(a):
                self.assertFalse(p["text"].startswith(s["title"] + " - "), p["label"])
                self.assertTrue(p["text"].strip())


if __name__ == "__main__":
    unittest.main()
