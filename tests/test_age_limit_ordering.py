"""Age questions: the section headed "Age limit" is moved to the front of the retrieved chunks (reorder only)."""

import unittest

from langchain_core.documents import Document

from backend import hybrid_retrieval as hr


def doc(pid, heading):
    return Document(page_content=pid, metadata={"provision_id": pid, "provision_heading": heading})


S7 = doc("Section 7", "Restrictions on the granting of learner’s licences for certain vehicles")
S4 = doc("Section 4", "Age limit in connection with driving of motor vehicles")
S8 = doc("Section 8", "Grant of learner’s licence")
DOCS = [S7, S4, S8]


class PromoteAgeLimit(unittest.TestCase):
    def ids(self, q, docs=DOCS):
        return [d.metadata["provision_id"] for d in hr.promote_age_limit(q, docs)]

    def test_age_questions_put_the_age_limit_section_first(self):
        for q in ["What is the minimum age for a learner's licence?", "how old do I need to be to drive a car",
                  "Age limit for driving a motorcycle", "Can a minor ride a scooter?"]:
            self.assertEqual(self.ids(q), ["Section 4", "Section 7", "Section 8"], q)

    def test_other_questions_keep_their_order(self):
        for q in ["How long is a learner's licence valid?", "Is it compulsory to wear a helmet?",
                  "What documents are required to apply for a driving licence?"]:
            self.assertEqual(self.ids(q), ["Section 7", "Section 4", "Section 8"], q)

    def test_it_only_reorders_never_adds_or_removes(self):
        out = hr.promote_age_limit("minimum age", DOCS)
        self.assertEqual(sorted(id(d) for d in out), sorted(id(d) for d in DOCS))

    def test_no_age_limit_section_leaves_the_list_unchanged(self):
        self.assertEqual(self.ids("minimum age", [S7, S8]), ["Section 7", "Section 8"])

    def test_missing_metadata_is_safe(self):
        self.assertEqual(len(hr.promote_age_limit("minimum age", [Document(page_content="x")])), 1)
        self.assertEqual(hr.promote_age_limit("", []), [])


if __name__ == "__main__":
    unittest.main()
