from django.test import SimpleTestCase

from ai_engineering.services.grading import compute_authoritative_grade, validate_score_range


class GradingServiceTests(SimpleTestCase):
    def test_grade_a_when_all_scores_high(self):
        result = compute_authoritative_grade(90, 90, 90)
        self.assertEqual(result.grade, "A")

    def test_grade_b_when_b_threshold_breached(self):
        result = compute_authoritative_grade(74, 90, 90)
        self.assertEqual(result.grade, "B")

    def test_grade_c_when_c_threshold_breached(self):
        result = compute_authoritative_grade(90, 69, 90)
        self.assertEqual(result.grade, "C")

    def test_boundary_values_keep_expected_grade(self):
        # Exact threshold values should not trigger lower grade because the rules use <
        result = compute_authoritative_grade(75, 80, 70)
        self.assertEqual(result.grade, "A")

    def test_validate_score_range_rejects_invalid_values(self):
        with self.assertRaises(ValueError):
            validate_score_range("color_score", -1)
        with self.assertRaises(ValueError):
            validate_score_range("color_score", 101)
