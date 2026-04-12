from dataclasses import dataclass

GRADING_POLICY_VERSION = "2026-04-v1"

GRADE_C_THRESHOLDS = {
    "color": 65.0,
    "size": 70.0,
    "ripeness": 60.0,
}

GRADE_B_THRESHOLDS = {
    "color": 75.0,
    "size": 80.0,
    "ripeness": 70.0,
}


@dataclass(frozen=True)
class GradeResult:
    grade: str
    derivation: str


def _as_float(name: str, value) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    return result


def validate_score_range(name: str, value) -> float:
    score = _as_float(name, value)
    if score < 0 or score > 100:
        raise ValueError(f"{name} must be between 0 and 100")
    return score


def compute_authoritative_grade(color_score, size_score, ripeness_score) -> GradeResult:
    color = validate_score_range("color_score", color_score)
    size = validate_score_range("size_score", size_score)
    ripeness = validate_score_range("ripeness_score", ripeness_score)

    if (
        color < GRADE_C_THRESHOLDS["color"]
        or size < GRADE_C_THRESHOLDS["size"]
        or ripeness < GRADE_C_THRESHOLDS["ripeness"]
    ):
        return GradeResult(
            grade="C",
            derivation="C because one or more values breached C thresholds",
        )

    if (
        color < GRADE_B_THRESHOLDS["color"]
        or size < GRADE_B_THRESHOLDS["size"]
        or ripeness < GRADE_B_THRESHOLDS["ripeness"]
    ):
        return GradeResult(
            grade="B",
            derivation="B because one or more values breached B thresholds",
        )

    return GradeResult(
        grade="A",
        derivation="A because all values met A thresholds",
    )
