from dataclasses import dataclass


@dataclass(frozen=True)
class RecommendationResult:
    action: str
    derivation: str


def build_recommendation(grade: str, confidence) -> RecommendationResult:
    confidence_value = float(confidence)

    if grade == "A":
        return RecommendationResult(
            action="KEEP_PRICE",
            derivation=f"Grade A with confidence {confidence_value:.2f}: keep normal pricing",
        )

    if grade == "B":
        if confidence_value >= 80:
            action = "MODERATE_MARKDOWN"
            reason = "Grade B with high confidence"
        else:
            action = "REVIEW_OR_SMALL_MARKDOWN"
            reason = "Grade B with uncertain confidence"
        return RecommendationResult(action=action, derivation=reason)

    return RecommendationResult(
        action="FAST_SALE_OR_HEAVY_MARKDOWN",
        derivation="Grade C indicates quality risk and faster stock movement is advised",
    )
