import itertools
import unittest

from backend.models import ChallengeFields
from backend.scoring import calculate_readiness, readiness_level


class ScoringTests(unittest.TestCase):
    def test_empty_and_whitespace(self):
        fields = ChallengeFields(context=" \n ", need="\t")
        result = calculate_readiness(fields)
        self.assertEqual(result.readiness_score, 0)
        self.assertEqual(result.readiness_level, "Draft")
        self.assertEqual(len(result.missing_information), 9)
        self.assertEqual(len(result.recommendations), 9)

    def test_all_combinations_have_exact_weights(self):
        weights = {"context": 10, "need": 10, "data_and_materials": 20,
                   "expected_result": 15, "success_criteria": 15,
                   "constraints": 10, "users": 10, "contact": 5,
                   "interaction_format": 5}
        for flags in itertools.product((False, True), repeat=len(weights)):
            supplied = {key: "Provided" for key, present in zip(weights, flags) if present}
            with self.subTest(fields=list(supplied)):
                result = calculate_readiness(ChallengeFields(**supplied))
                expected = sum(weights[key] for key in supplied)
                self.assertEqual(result.readiness_score, expected)
                self.assertEqual(sum(v.score for v in result.breakdown.values()), expected)
                self.assertEqual(sum(v.max_score for v in result.breakdown.values()), 100)
                self.assertEqual(set(result.missing_information), set(weights) - set(supplied))
                self.assertEqual(len(result.recommendations), len(weights) - len(supplied))

    def test_level_boundaries(self):
        for score, level in [(0, "Draft"), (39, "Draft"), (40, "Working"),
                             (69, "Working"), (70, "Ready"), (89, "Ready"),
                             (90, "Priority"), (100, "Priority")]:
            with self.subTest(score=score):
                self.assertEqual(readiness_level(score), level)

    def test_unweighted_fields_and_repeatability(self):
        fields = ChallengeFields(title="Task", industry="Retail", contact="Contact")
        first = calculate_readiness(fields)
        self.assertEqual(first.readiness_score, 5)
        self.assertEqual(first.breakdown["business_contact_interaction"].score, 5)
        self.assertEqual(first, calculate_readiness(fields))
