"""Deterministic completeness score, independent of any AI provider."""
from .models import ChallengeFields, Criterion, Readiness

CRITERIA = {
    "context_and_need": {"context": 10, "need": 10},
    "data_and_materials": {"data_and_materials": 20},
    "expected_result": {"expected_result": 15},
    "success_criteria": {"success_criteria": 15},
    "constraints": {"constraints": 10},
    "users": {"users": 10},
    "business_contact_interaction": {"contact": 5, "interaction_format": 5},
}
HINTS = {
    "context": "Опишите текущую ситуацию бизнеса",
    "need": "Укажите проблему или потребность",
    "data_and_materials": "Укажите доступные данные и материалы или явно сообщите об их отсутствии",
    "expected_result": "Опишите ожидаемый результат работы команды",
    "success_criteria": "Укажите проверяемые критерии успеха",
    "constraints": "Укажите ограничения или явно сообщите об их отсутствии",
    "users": "Укажите, кто будет пользоваться решением",
    "contact": "Добавьте контакт представителя бизнеса",
    "interaction_format": "Опишите формат взаимодействия с командой",
}


def readiness_level(score: int) -> str:
    if score < 40:
        return "Draft"
    if score < 70:
        return "Working"
    if score < 90:
        return "Ready"
    return "Priority"


def calculate_readiness(fields: ChallengeFields) -> Readiness:
    breakdown = {}
    missing = []
    recommendations = []
    for criterion, weights in CRITERIA.items():
        earned = 0
        for field, weight in weights.items():
            if getattr(fields, field).strip():
                earned += weight
            else:
                missing.append(field)
                recommendations.append(f"{HINTS[field]} (+{weight} баллов)")
        breakdown[criterion] = Criterion(score=earned, max_score=sum(weights.values()))
    score = sum(item.score for item in breakdown.values())
    return Readiness(
        readiness_score=score, readiness_level=readiness_level(score),
        breakdown=breakdown, missing_information=missing,
        recommendations=recommendations,
    )
