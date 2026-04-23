from dataclasses import dataclass

GRADING_POLICY_VERSION = "2026-04-v2"

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


def compute_authoritative_grade(color_score, size_score, ripeness_score, predicted_class=None) -> GradeResult:
    color = validate_score_range("color_score", color_score)
    size = validate_score_range("size_score", size_score)
    ripeness = validate_score_range("ripeness_score", ripeness_score)

    if predicted_class and isinstance(predicted_class, str) and predicted_class.strip().lower() == "rotten":
        return GradeResult(
            grade="C",
            derivation="C because severe classification defects (rot) were detected",
        )

    # 1. Hard Floor: Catch severely damaged or discoloured items
    if color < 35.0 or size < 40.0 or ripeness < 35.0:
        return GradeResult(
            grade="C",
            derivation="C because one or more values breached the hard floor minimums",
        )

    # 2. Weights: Colour 40%, Size 30%, Ripeness 30%
    weighted_score = (color * 0.40) + (size * 0.30) + (ripeness * 0.30)

    # 3. Calibrated Thresholds
    if weighted_score >= 68.0:
        return GradeResult(
            grade="A",
            derivation=f"A because weighted score {weighted_score:.1f} meets A threshold",
        )
    if weighted_score >= 50.0:
        return GradeResult(
            grade="B",
            derivation=f"B because weighted score {weighted_score:.1f} meets B threshold",
        )

    return GradeResult(
        grade="C",
        derivation=f"C because weighted score {weighted_score:.1f} falls below B threshold",
    )
