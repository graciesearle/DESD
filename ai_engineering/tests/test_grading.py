from django.test import SimpleTestCase
from ai_engineering.services.grading import compute_authoritative_grade, validate_score_range

class GradingServiceTests(SimpleTestCase):
    def test_grade_a_when_weighted_score_is_high(self):
        # Weighted: (76 * 0.3) + (74 * 0.4) + (88 * 0.3) = 78.8 (Grade A)
        result = compute_authoritative_grade(76, 74, 88)
        self.assertEqual(result.grade, "A")

    def test_grade_b_weighted_rescue(self):
        # A low colour score rescued by good shape/ripeness
        # Weighted: (40.4 * 0.3) + (74.4 * 0.4) + (65.5 * 0.3) = 61.5 (Grade B)
        result = compute_authoritative_grade(40.4, 74.4, 65.5)
        self.assertEqual(result.grade, "B")

    def test_grade_c_when_hard_floor_breached(self):
        # Even if weighted score is high, a size < 40 triggers the hard floor Grade C
        result = compute_authoritative_grade(90, 39, 90)
        self.assertEqual(result.grade, "C")

    def test_validate_score_range_rejects_invalid_values(self):
        with self.assertRaises(ValueError):
            validate_score_range("color_score", -1)
        with self.assertRaises(ValueError):
            validate_score_range("color_score", 101)