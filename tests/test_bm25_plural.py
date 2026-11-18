"""Stage 17: plural-only folding in BM25 tokenisation. Fixture text only; no Ollama, Chroma or model calls."""

import unittest

from langchain_core.documents import Document

from backend import hybrid_retrieval as hr


class FoldPluralTests(unittest.TestCase):
    def test_plurals_fold_to_singular(self):
        for word, want in [("certificates", "certificate"), ("issues", "issue"), ("drivers", "driver"),
                           ("conductors", "conductor"), ("vehicles", "vehicle"), ("penalties", "penalty"),
                           ("fees", "fee"), ("permits", "permit")]:
            self.assertEqual(hr.fold_plural(word), want, word)

    def test_no_other_suffixes_removed(self):
        for word in ("issuing", "issued", "licence", "medical", "parking", "status", "bus", "class", "pass"):
            self.assertEqual(hr.fold_plural(word), word)

    def test_short_words_numbers_and_identifiers_unchanged(self):
        for word in ("has", "was", "its", "12b", "83a", "go32y2026", "2026", "rules123"):
            self.assertEqual(hr.fold_plural(word), word)

    def test_tokenize_applies_fold_after_stopwords(self):
        self.assertEqual(hr.tokenize("Who issues medical certificates for drivers?"),
                         ["issue", "medical", "certificate", "driver"])

    def test_go_and_rule_tokens_survive(self):
        toks = hr.tokenize("G.O.Ms.No. 32 of 2026 and Rule 12 B")
        self.assertIn("rule", toks)
        self.assertFalse(any(t.startswith("go") and t[2:3].isdigit() and t != hr.fold_plural(t) for t in toks))

    def test_plural_query_matches_singular_provision_text(self):
        # Shape of TG-MR-008: the provision uses the singular, the question the plural.
        def doc(pid, text):
            return Document(page_content=text, metadata={"manifest_id": "m", "provision_id": pid, "part": 1,
                                                         "parts": 1, "location": pid, "state": "Telangana"})
        docs = [doc("Rule 77", "Issuing Authority of Medical Certificate. The Authority to issue a medical "
                               "certificate shall be an Assistant Civil Surgeon."),
                doc("Rule 1", "Drivers and conductors shall wear uniforms."),
                doc("Rule 2", "Fees for permits.")]
        bm25 = hr.BM25([hr.tokenize(d.page_content) for d in docs])
        scores = bm25.scores(hr.tokenize("Who issues medical certificates for drivers and for conductors?"))
        self.assertEqual(max(range(3), key=lambda i: scores[i]), 0)


if __name__ == "__main__":
    unittest.main()
