"""Stage 3E: provisos and other qualifications stated in their OWN sentence (backend/meaning_checks.py:
_proviso_parents, proviso_omitted).

A claim that restates a provision must also restate each proviso the passage connects to it - "Provided that",
"Provided further/also that", "Except that", or a "Notwithstanding <sub-rule>" provision - in one of its own
sentences or in a sibling claim citing the same passage. The connection is structural and conservative: when the
parent is unclear the proviso is associated with nothing.

REAL fixtures (RULE_*) are copied exactly from the stored index chunks (590-chunk Telangana index: tmvr-1989 chapters
4, 5 and 7); RealProvisoFixtureTests checks them against a copy of the real index when KYR_REAL_INDEX_DIR is set.
SYNTHETIC fixtures are labelled SYNTHETIC and are not legal text.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from backend import grounded_answer as ga
from backend import meaning_checks as mc
from test_grounded_answer import FUSED, FUSED_TEXT, SUBSTANTIVE, chunk, response, run
from test_view_source_real import INDEX_DIR, REQUIRED, missing

# --- REAL stored chunk text (exact) ------------------------------------------------------------------------------
RULE_108 = ('Telangana Motor Vehicles Rules, 1989 - Rule 108 - Form of application for grant or renewal of certif'
    'icate of fitness\n108. Form of application for grant or renewal of certificate of fitness :- (1) An a'
    'pplication for the grant or renewal of a certificate of fitness in respect of a motor vehicle shall '
    'be made in Form C.F.A. to the Inspector of Motor Vehicles or to the authorized testing station in wh'
    'ose jurisdiction the owner of the vehicle resides or carries on his business:\nProvided that in the c'
    'ase of a stage carriage such application may be made to the Inspector of Motor Vehicles or to the au'
    'thorized testing station in whose jurisdiction the owner of the vehicle resides or carries on his bu'
    'siness at either end of the route on which the vehicle is permitted to ply or proposed to be plied a'
    't the option of the owner of the vehicle which he may exercise by filing a declaration before the Se'
    'cretary of the Regional Transport Authority which granted or proposes to grant the said permit; and '
    'the option once exercised shall not be permitted to be revised unless in the opinion of the Secretar'
    'y of the said Authority, new circumstances have arisen warranting such revision.\n(2) Notwithstanding'
    ' the provisions of sub-rule (1) an application for renewal of a certificate of fitness can be made t'
    'o any other Inspector of Motor Vehicles or to any authorized testing station in whose jurisdiction t'
    'he vehicle is kept for the time being, with the permission of the Secretary of the Regional Transpor'
    't Authority which has granted the permit to the vehicle.')
RULE_109 = ('Telangana Motor Vehicles Rules, 1989 - Rule 109 - Date of next inspection – Endorsement on Certifica'
    'te\n109. Date of next inspection – Endorsement on Certificate :- The authority by whom a certificate '
    'of fitness was issued or, if it has been renewed, the authority, by whom it was last renewed, may en'
    'dorse thereon the date, time and place appointed for the next inspection of the vehicle and the owne'
    'r shall cause the vehicle to be produced accordingly:\nProvided that the vehicle need not be so produ'
    'ced if the owner proposes not to renew the certificate or if the vehicle is transferred to and kept '
    'in the area of another registering authority or Inspector of Motor Vehicles. In either of these case'
    's the owner shall, before the date fixed for inspection, inform the authority who made the endorseme'
    'nt, in writing, that he does not propose to produce the vehicle, giving the reasons.')
RULE_132 = ('Telangana Motor Vehicles Rules, 1989 - Rule 132 - Meeting of Regional Transport Authorities\n132. Mee'
    'ting of Regional Transport Authorities :- The Regional Transport Authority may meet once in three mo'
    'nths on such date and at such time and place as may be determined by the Chairman, and on such other'
    ' occasions, so determined as may be necessary for the prompt dispatch of business:\nProvided that the'
    ' Regional Transport Authority may meet before the aforesaid stipulated time according to exigencies '
    'and in the interest of public for prompt disposal of the business; if the total number of applicatio'
    'ns are more than fifty (50);\nProvided further that adequate notice of such meetings and of business '
    'to be transacted thereat shall be given for information of such persons who being interested in the '
    'particular business to be transacted may in the opinion of the Regional Transport Authority or if it'
    's Secretary reasonably claim to be permitted to attend for the purpose of making representations.')
RULE_210 = ('Telangana Motor Vehicles Rules, 1989 - Rule 210 - Endorsement of permits\n210. Endorsement of permits'
    ' :- The Transport Authority sanctioning an application for renewal of endorsement or extension of va'
    'lidity of a permit shall call upon the permit-holder to produce the permit, and endorse the renewal '
    'in the permit and return to the holder. The Transport Authority may revoke its sanction of the appli'
    'cation for renewal, if the permit-holder fails to produce the documents aforesaid within thirty days'
    ' from the date of receipt by him of the order requiring the production of the records :\nProvided tha'
    't the Secretary of the Transport Authority may, if satisfied on an application made to him in writin'
    'g by permit-holder within the period of thirty days aforesaid that there is sufficient ground, grant'
    ' an extension of time not exceeding four months in aggregate for the production of the records.')
RULE_337 = ('Telangana Motor Vehicles Rules, 1989 - Rule 337 - Seats for conductors and drivers\n337. Seats for co'
    'nductors and drivers :- (1) On every stage carriage there shall be provided for the conductor a reas'
    'onably comfortable seating space of not less than 381 millimeters square so located as to allow him '
    'at all times a complete view of the inside of the vehicle :\nProvided that in the case of stage carri'
    'age operating within the limits of a town or city a ‘standing seat’ will be sufficient, if so, speci'
    'ally declared by the Regional Transport Authority.\n(2) On every public service vehicle space shall b'
    'e reserved for the driver’s seat such as to allow him to have complete control of the vehicle and in'
    ' particular:-\n(i)the part of the seat against which the driver’s back rests shall not be less than 2'
    '79 millimeters from the nearest point on the steering wheel;\n(ii)the width across the vehicle shall '
    'be not less than 686 millimeters shall extend to the left of centre of the steering column in no cas'
    'e less than 254 millimeters so that the line drawn parallel to axis of the vehicle through the centr'
    'e of any gear lever, brake lever or other device to which the driver has to have frequent access lie'
    's not less than 51 millimeters inside the width reserved for the driver’s seat; and\n(iii)in the case'
    ' of public service vehicle other than a motor cab, the space reserved in accordance with Clause (ii)'
    ' shall at the left hand end be enclosed with a suitable partition to a height not less than 305 mill'
    'imeters above the seat.\n(3)Any arm rests for the driver not more than 102 millimeters wide may be pr'
    'ovided within the space specified in Clause (ii) of sub-rule (2):\nProvided that sub-rules (2)(ii) an'
    'd (3) shall not apply in the case of a stage carriage of full forward control.')

REAL = {("tmvr-1989-chap-4", "Rule 108"): RULE_108, ("tmvr-1989-chap-4", "Rule 109"): RULE_109,
        ("tmvr-1989-chap-5", "Rule 132"): RULE_132, ("tmvr-1989-chap-5", "Rule 210"): RULE_210,
        ("tmvr-1989-chap-7", "Rule 337"): RULE_337}

# --- SYNTHETIC fixtures (not legal text; every string below that is not a RULE_* constant is synthetic) -------------------------------------------------------------------------
SYN_NOTWITHSTANDING = ("(1) A permit shall be renewed by the Regional Transport Authority. "
                       "(2) Notwithstanding anything contained in sub-rule (1), a permit for a vehicle older than "
                       "fifteen years shall not be renewed.")
SYN_EXCEPT_THAT = ("Every learner shall be accompanied by a licensed instructor. Except that a "
                   "learner on a motor cycle without a pillion seat need not be accompanied.")
SYN_UNRELATED_NEIGHBOUR = ("Every application shall be made in writing. The fee shall be paid in "
                           "cash. Provided that the fee may be paid online.")
SYN_LIST = ("The owner shall:- (a) keep the certificate in the vehicle; (b) produce it on demand. "
            "Provided that a copy may be produced.")


def sentences(text):
    return mc.sentences(text)


def body(sentence):
    return mc._strip_title(sentence)


def doc(key):
    return chunk(key[0], key[1], REAL[key])


R108, R109, R132, R210, R337 = (sentences(REAL[k]) for k in sorted(REAL))
K108, K109, K132, K210, K337 = sorted(REAL)


def parents(text):
    ss = sentences(text)
    return {ss[k][:40]: [ss[j][:40] for j in js] for k, js in mc._proviso_parents(ss).items()}


class ProvisoAssociation(unittest.TestCase):
    """How a proviso is connected to its parent sentence (real stored chunks first)."""

    def test_real_rule_109_proviso_qualifies_the_preceding_provision_only(self):
        p = mc._proviso_parents(R109)
        self.assertEqual(p, {2: (1,)})                       # [3] "In either of these cases ..." is not a proviso
        self.assertTrue(R109[1].endswith("accordingly:"))   # the parent ends with ':' - proviso punctuation

    def test_real_rule_132_provided_further_chains_to_the_same_parent(self):
        self.assertEqual(mc._proviso_parents(R132), {2: (1,), 3: (1,)})

    def test_real_rule_108_notwithstanding_sub_rule_1_targets_sub_rule_1(self):
        p = mc._proviso_parents(R108)
        self.assertEqual(p, {2: (1,), 3: (1,)})             # sub-rule (1) is fused to the heading in sentence 1
        self.assertTrue(R108[3].startswith("(2) Notwithstanding the provisions of sub-rule (1)"))

    def test_real_rule_210_proviso_attaches_to_its_own_sentence_not_the_neighbour(self):
        self.assertEqual(mc._proviso_parents(R210), {3: (2,)})

    def test_real_rule_337_proviso_of_sub_rule_1_is_not_associated_with_sub_rule_2(self):
        p = mc._proviso_parents(R337)
        self.assertEqual(p[2], (1,))
        self.assertTrue(R337[3].startswith("(2)"))
        self.assertFalse(any(3 <= j for js in p.values() for j in js))
        # known limitation, documented here: a compound target ("sub-rules (2)(ii) and (3) shall not apply") is
        # not resolved, so that proviso is associated with nothing (no finding, rather than a guessed parent)
        self.assertNotIn(8, p)

    def test_synthetic_structures(self):
        self.assertEqual(mc._proviso_parents(sentences(SYN_NOTWITHSTANDING)), {1: (0,)})
        self.assertEqual(mc._proviso_parents(sentences(SYN_EXCEPT_THAT)), {1: (0,)})
        self.assertEqual(mc._proviso_parents(sentences(SYN_UNRELATED_NEIGHBOUR)), {2: (1,)})
        self.assertEqual(mc._proviso_parents(sentences(SYN_LIST)), {})  # after a list item: parent unclear

    def test_unclear_parents_are_not_guessed(self):
        for text in ("Provided that the fee may be paid online.",                                 # nothing before
                     "Synthetic Motor Rules - Rule 905 - Fees\nProvided that the fee may be paid online.",      # only a header
                     "Fees are payable. The form is free. Provided further that no fee is "
                     "payable by a widow.",                                                         # broken chain
                     "Fees are payable. Notwithstanding anything in these rules, no fee is "
                     "payable by a widow.",                                                         # whole-rules scope
                     "(1) Fees are payable. (2) Fees are refundable. Provided that clauses (a) "
                     "and (b) shall not apply to widows."):                                         # compound target
            self.assertEqual(mc._proviso_parents(sentences(text)), {}, text)

    def test_subject_to_opening_a_sentence_is_not_a_proviso_of_the_previous_one(self):
        ss = sentences("Fees are payable. Subject to Rule 12, the fee is refundable.")
        self.assertEqual(mc._proviso_parents(ss), {})

    def test_same_line_proviso_after_a_colon_is_its_own_sentence(self):
        ss = sentences("The owner shall produce the vehicle: Provided that a copy may be shown.")
        self.assertEqual(len(ss), 2)
        self.assertEqual(mc._proviso_parents(ss), {1: (0,)})


class ProvisoValidation(unittest.TestCase):
    """The full validation path (grounded_answer.validate) on real stored chunks."""

    def check(self, keys, *claims):
        contract, _ = ga.build_contract("q", [doc(k) for k in keys], "r")
        return ga.validate(response(claims=list(claims)), contract)

    def assertRejectedFor(self, check, result):
        self.assertFalse(result.ok)
        self.assertIn(check, {c["check"] for c in result.checks}, result.errors)

    # 1. main provision + connected proviso: omission rejected
    def test_1_omitted_connected_proviso_rejected(self):
        self.assertRejectedFor("proviso_omitted", self.check([K109], (body(R109[1]), "direct", ["E1"])))
        self.assertRejectedFor("proviso_omitted", self.check([K210], (R210[2], "direct", ["E1"])))
        self.assertRejectedFor("proviso_omitted", self.check([K337], (body(R337[1]), "direct", ["E1"])))
        result, _ = run("When must a vehicle be produced for inspection?", [doc(K109)],
                        response(claims=[(body(R109[1]), "direct", ["E1"])]))
        self.assertEqual(result.kind, "rejected")

    # 2. main provision + correctly represented proviso: accepted
    def test_2_represented_proviso_accepted(self):
        faithful = ("However, the vehicle need not be produced if the owner proposes not to renew the certificate or "
                    "if the vehicle is transferred to and kept in the area of another registering authority.")
        for key, claims in ((K109, [(body(R109[1]), "direct", ["E1"]), (R109[2], "direct", ["E1"])]),  # 2 claims
                            (K109, [(body(R109[1]) + " " + R109[2], "direct", ["E1"])]),               # 1 claim
                            (K109, [(body(R109[1]), "direct", ["E1"]), (faithful, "direct", ["E1"])]),  # paraphrase
                            (K210, [(R210[2], "direct", ["E1"]), (R210[3], "direct", ["E1"])]),
                            (K337, [(body(R337[1]), "direct", ["E1"]), (R337[2], "direct", ["E1"])])):
            result = self.check([key], *claims)
            self.assertTrue(result.ok, (claims[0][0][:50], result.errors))
        result, _ = run("When must a vehicle be produced for inspection?", [doc(K109)],
                        response(claims=[(body(R109[1]), "direct", ["E1"]), (R109[2], "direct", ["E1"])]))
        self.assertEqual(result.kind, "answer", result.errors)
        self.assertEqual([(e.document_id, e.provision_id) for e in result.cited], [("tmvr-1989-chap-4", "Rule 109")])

    def test_2b_represented_proviso_must_itself_be_faithful(self):
        main = (body(R109[1]), "direct", ["E1"])
        for changed, check in (
                ("The vehicle need not be so produced if the owner proposes to renew the certificate or if the "
                 "vehicle is transferred to and kept in the area of another registering authority or Inspector of "
                 "Motor Vehicles.", "qualifier_altered"),                                        # negation reversed
                ("The vehicle shall not be produced if the owner proposes not to renew the certificate or if the "
                 "vehicle is transferred to and kept in the area of another registering authority or Inspector of "
                 "Motor Vehicles.", "deontic"),                                                  # 'need not' -> 'shall not'
                ("The vehicle need not be so produced if the owner proposes not to renew the certificate.",
                 "proviso_omitted"),                                                             # a condition dropped
                ("Some exceptions apply.", "proviso_omitted")):                                  # vague
            self.assertRejectedFor(check, self.check([K109], main, (changed, "direct", ["E1"])))

    # 3. unrelated neighbouring sentence or proviso: no rejection
    def test_3_unrelated_neighbour_does_not_trigger(self):
        self.assertTrue(self.check([K210], (body(R210[1]), "direct", ["E1"])).ok)    # proviso belongs to [2]
        self.assertTrue(self.check([K109], (body(R109[1]), "direct", ["E1"]),
                                   (R109[2], "direct", ["E1"])).ok)                    # [3] not required
        r = mc.check_claim("Every application shall be made in writing.", "direct", {"E1": SYN_UNRELATED_NEIGHBOUR},
                           {}, strip=ga.strip_identifiers, definitive=True, id_fn=ga.identifiers)
        self.assertNotIn("proviso_omitted", [c for c, _m in r])

    # 4. proviso of another sub-rule: not associated
    def test_4_proviso_of_another_sub_rule_not_associated(self):
        self.assertTrue(self.check([K337], (R337[4], "direct", ["E1"])).ok)          # (2)(i): (1)'s proviso n/a
        self.assertTrue(self.check([K337], (R337[3], "direct", ["E1"])).ok)

    # 5. "Provided further that"
    def test_5_provided_further_required(self):
        main, p1, p2 = (body(R132[1]), "direct", ["E1"]), (R132[2], "direct", ["E1"]), (R132[3], "direct", ["E1"])
        self.assertRejectedFor("proviso_omitted", self.check([K132], main, p1))
        self.assertRejectedFor("proviso_omitted", self.check([K132], main, p2))
        self.assertTrue(self.check([K132], main, p1, p2).ok)
        self.assertTrue(self.check([K132], p2).ok)                                     # a proviso alone: fine

    # 6. "Notwithstanding" (real Rule 108 is checked at the meaning layer: its sub-rule (1) is over the 600-character
    # claim limit, so no complete quotation can pass the schema)
    def test_6_notwithstanding_required(self):
        def findings(claim, passage, *sibs):
            return [c for c, _m in mc.check_claim(claim, "direct", {"E1": passage}, {}, strip=ga.strip_identifiers,
                                                  definitive=True, siblings=tuple((s, ("E1",)) for s in sibs),
                                                  id_fn=ga.identifiers)]
        main = body(R108[1])
        self.assertEqual(findings(main, RULE_108).count("proviso_omitted"), 2)
        self.assertEqual(findings(main, RULE_108, R108[2]).count("proviso_omitted"), 1)  # the (2) override missing
        self.assertNotIn("proviso_omitted", findings(main, RULE_108, R108[2], R108[3]))
        self.assertNotIn("proviso_omitted", findings(R108[3], RULE_108))                # the override alone
        # SYNTHETIC: through the full validation path
        contract, _ = ga.build_contract("q", [chunk("tmvr-1989-chap-5", "Rule 901", SYN_NOTWITHSTANDING)], "r")
        renew = ("A permit shall be renewed by the Regional Transport Authority.", "direct", ["E1"])
        override = ("A permit for a vehicle older than fifteen years shall not be renewed, notwithstanding anything "
                    "contained in sub-rule (1).", "direct", ["E1"])
        self.assertRejectedFor("proviso_omitted", ga.validate(response(claims=[renew]), contract))
        self.assertTrue(ga.validate(response(claims=[renew, override]), contract).ok)

    def test_except_that(self):  # SYNTHETIC
        contract, _ = ga.build_contract("q", [chunk("tmvr-1989-chap-5", "Rule 902", SYN_EXCEPT_THAT)], "r")
        main = ("Every learner shall be accompanied by a licensed instructor.", "direct", ["E1"])
        self.assertRejectedFor("proviso_omitted", ga.validate(response(claims=[main]), contract))
        self.assertTrue(ga.validate(response(claims=[main, ("A learner on a motor cycle without a pillion seat need "
                                                            "not be accompanied.", "direct", ["E1"])]), contract).ok)

    # 7. Stage 3C exact helmet quotation (Rule 437 has no proviso)
    def test_7_stage_3c_helmet_quote_still_accepted(self):
        result, _ = run("What are the helmet requirements?", [FUSED], response(claims=[(SUBSTANTIVE, "direct", ["E1"])]))
        self.assertEqual(result.kind, "answer", result.errors)
        self.assertEqual(result.contract.evidence[0].passage, FUSED_TEXT)

    # 10. unrelated evidence
    def test_10_proviso_cited_to_unrelated_evidence_rejected(self):
        result = self.check([K109, K132], (body(R109[1]), "direct", ["E1"]), (R109[2], "direct", ["E2"]))
        self.assertRejectedFor("proviso_omitted", result)                    # E2 does not state E1's proviso
        self.assertFalse(self.check([K132], (R109[2], "direct", ["E1"])).ok)


class NegationInsideAKeptCondition(unittest.TestCase):
    """Added with Stage 3E: once a proviso is compared without its connective, a reversed negation inside its kept
    condition must still be caught (it was only rejected before by accident of the garbled split)."""

    def findings(self, claim, passage):
        return [c for c, _m in mc.check_claim(claim, "direct", {"E1": passage}, {}, strip=ga.strip_identifiers,
                                              definitive=True)]

    def test_reversed_negation_in_a_condition_rejected(self):  # SYNTHETIC
        passage = "The fee shall be refunded if the owner does not renew the certificate."
        self.assertIn("qualifier_altered", self.findings("The fee shall be refunded if the owner renews the "
                                                         "certificate.", passage))
        self.assertEqual(self.findings("The fee shall be refunded if the owner does not renew the certificate.",
                                       passage), [])


class RealProvisoFixtureTests(unittest.TestCase):
    """The REAL fixtures above are the stored chunks, and associations over the whole index stay structural."""

    @classmethod
    def setUpClass(cls):
        reason = missing()
        if reason and REQUIRED:
            raise AssertionError(f"real backend test required but cannot run: {reason}")
        if reason:
            raise unittest.SkipTest(reason)
        import chromadb
        tmp = tempfile.mkdtemp(prefix="kyr-real-proviso-")
        cls.addClassCleanup(shutil.rmtree, tmp, ignore_errors=True)
        shutil.copytree(INDEX_DIR, Path(tmp) / "index")
        client = chromadb.PersistentClient(path=str(Path(tmp) / "index"))
        cls.rows = []
        for col in client.list_collections():
            col = client.get_collection(getattr(col, "name", col))
            got = col.get(include=["documents", "metadatas"])
            cls.rows += list(zip(got["documents"], got["metadatas"]))

    def test_fixtures_are_the_stored_chunks(self):
        stored = {(m.get("manifest_id"), m.get("provision_id")): d for d, m in self.rows if m.get("answer_eligible")}
        for key, text in REAL.items():
            self.assertEqual(stored.get(key), text, key)

    def test_parents_are_enacting_sentences_of_the_same_passage(self):
        associated = 0
        for d, m in self.rows:
            if not m.get("answer_eligible"):
                continue
            ss = sentences(d)
            for k, js in mc._proviso_parents(ss).items():
                associated += 1
                for j in js:
                    self.assertNotEqual(j, k)
                    self.assertFalse(mc._PROVISO_RE.match(ss[j]) and mc._PROVISO_RE.match(ss[j]).group(1), ss[j])
                    self.assertFalse(j == 0 and mc._HEADER_RE.search(ss[j]), ss[j])
        self.assertGreater(associated, 100)


if __name__ == "__main__":
    unittest.main()
