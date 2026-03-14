from __future__ import annotations


def score_regime(value: str) -> int:
    return {
        "yes": 30,
        "partial": 15,
        "no": 0,
    }[value]


def score_direction(value: str) -> int:
    return {
        "yes": 30,
        "no": 0,
    }[value]


def score_timing(value: str) -> int:
    return {
        "on_time": 20,
        "early": 10,
        "late": 10,
        "wrong": 0,
    }[value]


def score_magnitude(value: str) -> int:
    return {
        "close": 20,
        "under": 10,
        "over": 10,
        "wrong": 0,
    }[value]


def overall_prediction_score(
    *,
    regime_correct: str,
    direction_correct: str,
    timing_correct: str,
    magnitude_correct: str,
) -> int:
    return (
        score_regime(regime_correct)
        + score_direction(direction_correct)
        + score_timing(timing_correct)
        + score_magnitude(magnitude_correct)
    )
