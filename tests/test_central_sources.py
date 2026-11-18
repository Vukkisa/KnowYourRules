"""The Central sources (Motor Vehicles Act extract and the Driving Regulations) are served beside the Telangana sources, never as them.

These tests read the real files shipped with the repository: the Central manifest, its chunk flags, the three source files and
the source-status registry. They never open the index or call a model.
"""
import hashlib
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import build_telangana_index as bt, document_lifecycle as dl, grounded_answer as ga, source_status as ss  # noqa: E402
from backend import tg_ingest as ti, tg_manifest as tm  # noqa: E402

DIR = ROOT / "docs" / "legal-sources" / "telangana-traffic"
CORPUS = DIR / "source-documents"
MANIFEST = DIR / "CENTRAL-manifest.json"
FLAGS = DIR / "CENTRAL-chunk-flags.json"
REGISTRY = ROOT / "legal-status" / "source-status.json"

ACT = "mva-1988-india-code-extract"
REGS = "mvdr-2017-gsr-634e"
AMEND = "mvdr-2020-amendment-gsr-586e"


def available():
    return MANIFEST.is_file() and FLAGS.is_file() and (CORPUS / "central").is_dir()


@unittest.skipUnless(available(), "Central sources are not in this checkout")
class CentralManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entries = tm.load_manifest(MANIFEST)
        cls.by_id = {e.id: e for e in cls.entries}

    def test_the_manifest_is_central_only_and_its_files_match_their_hashes(self):
        self.assertEqual({e.jurisdiction for e in self.entries}, {"Central"})
        self.assertEqual(set(self.by_id), {ACT, REGS, AMEND})
        self.assertEqual(tm.file_errors(self.entries, CORPUS), [])

    def test_a_manifest_cannot_mix_jurisdictions(self):
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        data["documents"][0]["jurisdiction"] = "Telangana"
        with self.assertRaises(tm.ManifestError) as cm:
            tm.parse_manifest(data)
        self.assertIn("mixed jurisdictions", str(cm.exception))
        data["documents"][0]["jurisdiction"] = "Central"
        data["jurisdiction"] = "Andhra Pradesh"
        with self.assertRaises(tm.ManifestError):
            tm.parse_manifest(data)

    def test_nothing_central_is_marked_verified_or_draft(self):
        for e in self.entries:
            self.assertEqual(e.verification_status, "unverified", e.id)
            self.assertEqual(e.source_class, "official", e.id)
            self.assertIn("CENTRAL", e.notes, e.id)
            self.assertEqual(e.validity_status, tm.UNKNOWN, e.id)    # no verified validity dates are claimed

    def test_the_extract_says_where_it_came_from(self):
        text = (CORPUS / "central" / "mva-1988-india-code-extract.html").read_text(encoding="utf-8")
        self.assertIn("c619755eabb2085ec5ef8068777724223f3ec7e1cc1170aee0dd1608216dc482", text)   # the India Code file it was cut from
        self.assertIn("not a Gazette print", text)
        self.assertIn("This extract contains no penalty provisions", text)
        self.assertIn("c619755eabb2085ec5ef8068777724223f3ec7e1cc1170aee0dd1608216dc482", self.by_id[ACT].notes)

    def test_the_status_registry_never_calls_a_central_source_verified(self):
        data = json.loads(REGISTRY.read_text(encoding="utf-8"))
        rows = {e["manifest_id"]: e for e in data["entries"] if e["manifest_id"] in self.by_id}
        self.assertEqual(set(rows), set(self.by_id))
        for mid, row in rows.items():
            self.assertEqual(row["sha256"], self.by_id[mid].sha256)
            self.assertEqual(row["status"], "official_text_commencement_unconfirmed", mid)
            self.assertIsNone(row["review"]["decision"], mid)
        warning = ss.TEMPLATES["official_text_commencement_unconfirmed"].format(label="X")
        self.assertIn("not been confirmed that this is the latest in-force version", warning)


@unittest.skipUnless(available(), "Central sources are not in this checkout")
class CentralChunkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entries = tm.load_manifest(MANIFEST)
        cls.chunks = {}
        for e in cls.entries:
            blocks = ti.load_blocks(CORPUS / e.file, e.format, e.file)
            cls.chunks[e.id] = ti.chunk_document(blocks, e)
        flags = bt.load_chunk_flags(FLAGS)
        for e in cls.entries:
            problems = bt.apply_chunk_flags(cls.chunks[e.id], [f for f in flags if f["match"]["manifest_id"] == e.id])
            assert not problems, problems

    def ids(self, mid):
        return {c.metadata["provision_id"] for c in self.chunks[mid]}

    def test_every_central_chunk_is_tagged_central_and_valid(self):
        for e in self.entries:
            self.assertEqual(dl.validate_chunks(self.chunks[e.id], e.sha256, "Central"), [], e.id)
            self.assertTrue(all(c.metadata["state"] == "Central" == c.metadata["jurisdiction"] for c in self.chunks[e.id]))
            self.assertTrue(all(c.metadata["source_class"] == "official" for c in self.chunks[e.id]))
        # and they would not pass as Telangana chunks
        self.assertTrue(dl.validate_chunks(self.chunks[ACT], self.by_sha(ACT), "Telangana"))

    def by_sha(self, mid):
        return next(e.sha256 for e in self.entries if e.id == mid)

    def test_the_act_extract_has_the_expected_sections_each_in_its_own_chunk(self):
        sections = {f"Section {n}" for n in (3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 39, 40, 41, 50, 56, 112, 128, 129, 130, 134, 146)}
        self.assertEqual(self.ids(ACT) - {"Preamble"}, sections)
        # Section 129 (helmets) must not be folded into section 128's chunk, which would cite it under the wrong number.
        by = {c.metadata["provision_id"]: c.page_content for c in self.chunks[ACT]}
        self.assertIn("protective headgear", by["Section 129"])
        self.assertNotIn("Wearing of protective headgear.—", by["Section 128"])
        self.assertIn("eighteen years", by["Section 4"])

    def test_the_act_extract_holds_no_penalty_chapter(self):
        text = " ".join(c.page_content for c in self.chunks[ACT])
        self.assertNotIn("imprisonment", text)
        self.assertFalse(any(int(re.sub(r"\D", "", p)) >= 177 for p in self.ids(ACT) if p.startswith("Section ")))

    def test_the_regulations_are_numbered_and_the_unreadable_hindi_front_matter_is_not_used_to_answer(self):
        self.assertTrue({f"Regulation {n}" for n in (10, 12, 14, 16, 29, 37, 38)} <= self.ids(REGS))
        front = [c for c in self.chunks[REGS] if c.metadata["provision_id"] == "Preamble"]
        eligible = [c for c in front if c.metadata["answer_eligible"]]
        self.assertEqual(len(eligible), 1)                       # only the English enacting words
        self.assertIn("in supersession of the Rules of the Road Regulations, 1989", eligible[0].page_content)
        self.assertTrue(all(c.metadata["extraction_warning"] for c in front if not c.metadata["answer_eligible"]))

    def test_the_amendment_is_labelled_as_the_amending_text(self):
        flagged = [c for c in self.chunks[AMEND] if c.metadata["provision_id"] == "Regulation 37"]
        self.assertTrue(flagged and all("amending regulations" in c.metadata["extraction_warning"] for c in flagged))
        self.assertIn("physical or electronic form", " ".join(" ".join(c.page_content for c in flagged).split()))

    def test_the_grounded_prompt_names_the_jurisdiction_of_each_passage(self):
        chunk = next(c for c in self.chunks[ACT] if c.metadata["provision_id"] == "Section 4")
        contract, kept = ga.build_contract("What is the minimum age for a driving licence?", [chunk])
        self.assertEqual(len(kept), 1)
        self.assertEqual(contract.evidence[0].jurisdiction, "Central")
        self.assertIn('"jurisdiction": "Central"', ga.build_prompt(contract))


@unittest.skipUnless(available(), "Central sources are not in this checkout")
class ActHeadingTests(unittest.TestCase):
    """An Act section's heading is fused to its first sub-section in the source ("Title.—(1) text"). The heading is not part
    of that sentence, so a claim quoting the sub-section must be compared with the sub-section alone."""

    @classmethod
    def setUpClass(cls):
        e = next(x for x in tm.load_manifest(MANIFEST) if x.id == ACT)
        blocks = ti.load_blocks(CORPUS / e.file, e.format, e.file)
        cls.chunks = {}
        for c in ti.chunk_document(blocks, e):
            cls.chunks.setdefault(c.metadata["provision_id"], c)      # the first part of a provision that spans two chunks

    def claim(self, chunk, text):
        raw = json.dumps({"answer": text, "evidence_sufficiency": "sufficient", "refusal_reason": None,
                          "clarification_question": None, "citations": ["E1"],
                          "claims": [{"text": text, "kind": "direct", "evidence_ids": ["E1"]}]})
        contract, _ = ga.build_contract("question", [chunk])
        return ga.validate(raw, contract)

    def test_the_heading_is_its_own_sentence(self):
        from backend import meaning_checks as mc
        sents = mc.sentences(self.chunks["Section 14"].page_content)
        self.assertIn("Currency of licences to drive motor vehicles", sents)
        self.assertTrue(any(s.startswith("(1) A learner") for s in sents))

    def test_a_sentence_with_a_modal_is_never_taken_for_a_heading(self):
        from backend import meaning_checks as mc
        text = "The fee shall be paid.—(1) The applicant pays it."
        self.assertEqual(mc.sentences(text), [text])

    def test_a_faithful_quotation_of_a_sub_section_passes(self):
        self.assertTrue(self.claim(self.chunks["Section 14"], "A learner’s licence issued under this Act shall, subject to the "
                                   "other provisions of this Act, be effective for a period of six months from the date of "
                                   "issue of the licence.").ok)
        # sub-section (1) keeps the proviso that the source attaches to it; leaving it out is still rejected
        self.assertTrue(self.claim(self.chunks["Section 4"], "No person under the age of eighteen years shall drive a motor "
                                   "vehicle in any public place: Provided that a motor cycle with engine capacity not "
                                   "exceeding 50cc may be driven in a public place by a person after attaining the age of "
                                   "sixteen years.").ok)
        self.assertFalse(self.claim(self.chunks["Section 4"], "No person under the age of eighteen years shall drive a motor "
                                    "vehicle in any public place.").ok)

    def test_dropping_a_condition_or_changing_a_value_is_still_rejected(self):
        # "Subject to the provisions of section 18" and "twenty years" belong to sub-section (2); a claim that changes them fails
        bad = self.claim(self.chunks["Section 4"], "No person under the age of twenty years shall drive a transport vehicle "
                         "in any public place.")
        self.assertFalse(bad.ok)
        wrong = self.claim(self.chunks["Section 14"], "A learner’s licence issued under this Act shall, subject to the other "
                           "provisions of this Act, be effective for a period of one year from the date of issue of the licence.")
        self.assertFalse(wrong.ok)


    def claims(self, chunk, texts):
        raw = json.dumps({"answer": " ".join(texts), "evidence_sufficiency": "sufficient", "refusal_reason": None,
                          "clarification_question": None, "citations": ["E1"],
                          "claims": [{"text": t, "kind": "direct", "evidence_ids": ["E1"]} for t in texts]})
        contract, _ = ga.build_contract("question", [chunk])
        return ga.validate(raw, contract)

    SECTION_56 = ("Subject to the provisions of sections 59 and 60, a transport vehicle shall not be deemed to be validly "
                  "registered for the purposes of section 39, unless it carries a certificate of fitness in such form "
                  "containing such particulars and information as may be prescribed by the Central Government, issued by the "
                  "prescribed authority, or by an authorised testing station mentioned in sub-section (2), to the effect that "
                  "the vehicle complies for the time being with all the requirements of this Act and the rules made "
                  "thereunder")
    PROVISO_1 = ("Provided that where the prescribed authority or the authorised testing station refuses is issue such "
                 "certificate, it shall supply the owner of the vehicle with its reasons in writing for such refusal.")
    PROVISO_2 = ("Provided further that no certificate of fitness shall be granted to a vehicle, after such date as may be "
                 "notified by the Central Government, unless such vehicle has been tested at an automated testing station.")

    def test_provisos_printed_inside_amendment_brackets_are_separate_sentences(self):
        # "... refusal. 1[Provided further that ... station.] 2[(2) The ..." is one printed line; the markers are not words
        from backend import meaning_checks as mc
        sents = mc.sentences(self.chunks["Section 56"].page_content)
        self.assertTrue(any(s.startswith("Provided further that no certificate of fitness") for s in sents))
        self.assertTrue(any(s.startswith("(2) The “authorised testing station”") for s in sents))
        self.assertFalse(any("1[" in s or "]" in s for s in sents))

    def test_a_sentence_and_its_provisos_quoted_in_full_pass(self):
        chunk = self.chunks["Section 56"]
        self.assertTrue(self.claims(chunk, [self.SECTION_56 + ":", self.PROVISO_1, self.PROVISO_2]).ok)
        self.assertTrue(self.claims(chunk, [self.SECTION_56 + ".", self.PROVISO_1, "1[" + self.PROVISO_2 + "]"]).ok)

    def test_leaving_out_a_proviso_or_changing_a_section_number_is_still_rejected(self):
        chunk = self.chunks["Section 56"]
        self.assertFalse(self.claims(chunk, [self.SECTION_56 + "."]).ok)
        self.assertFalse(self.claims(chunk, [self.SECTION_56 + ".", self.PROVISO_1]).ok)
        self.assertFalse(self.claims(chunk, [self.SECTION_56.replace("59 and 60", "58 and 60") + ".", self.PROVISO_1,
                                             self.PROVISO_2]).ok)
        self.assertFalse(self.claims(chunk, [self.SECTION_56 + ".", self.PROVISO_1,
                                             self.PROVISO_2.replace("no certificate", "a certificate")]).ok)


class InstructionTests(unittest.TestCase):
    def test_the_instructions_keep_central_rules_out_and_central_law_separate(self):
        text = ga.ANSWER_INSTRUCTIONS
        self.assertIn("The Central Motor Vehicles Rules, 1989 are NOT in the evidence", text)
        self.assertIn("never explain a Central provision from such a citation", " ".join(text.split()))
        self.assertIn("Keep Central and Telangana law in separate", " ".join(text.split()))
        self.assertIn("restates ONE sentence", " ".join(text.split()))      # claims copy one sentence, so the meaning checks can run
        self.assertIn("do not say what\n   the prescribing rules contain", text)
        self.assertIn("Do not state, estimate or calculate penalties", text)     # the penalty refusal is untouched
        flat = " ".join(text.split())
        self.assertIn('only when NO passage states anything that answers the question', flat)   # a stated point is answered, not refused
        self.assertIn("refusal_reason of one short sentence", flat)
        self.assertIn("do not add a closing summary", flat)


if __name__ == "__main__":
    unittest.main()
