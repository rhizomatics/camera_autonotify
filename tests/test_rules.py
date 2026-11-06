"""Rules on a notification's message, with the suggested rules for risk levels, against real descriptions"""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.camera_autonotify.rules import Outcome, Rule, apply_rules, rank

# the rules suggested in the docs, for a description prompt that starts with a risk level
SUGGESTED: list[dict[str, Any]] = [
    {"name": "Critical risk", "match": "regex", "pattern": r"^critical risk\W*", "priority": "critical", "remove": True},
    {"name": "High risk", "match": "regex", "pattern": r"^high risk\W*", "priority": "high", "remove": True},
    {"name": "Medium risk", "match": "regex", "pattern": r"^medium risk\W*", "priority": "medium", "remove": True},
    {"name": "No or low risk", "match": "regex", "pattern": r"^(no|low) risk\b", "silence": True},
    {"name": "Unclear", "match": "regex", "pattern": r"^(unclear|unknown|uncertain)\b", "silence": True},
    {"name": "Birds", "match": "starts_with", "pattern": "bird identified", "priority": "minimum", "remove": True},
]


def rules(*data: dict[str, Any]) -> list[Rule]:
    built = [Rule.from_data(d["name"], d) for d in data]
    return [rule for rule in built if rule is not None]


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        # as Frigate wrote them, `RISK.`, `RISK:` and `RISK` with a space
        (
            "MEDIUM RISK. A person in green is crouching and moving fast near the open barn door.",
            Outcome(
                "A person in green is crouching and moving fast near the open barn door.", "medium", matched=("Medium risk",)
            ),
        ),
        (
            "MEDIUM RISK: Unidentified car at the pend entrance at night.",
            Outcome("Unidentified car at the pend entrance at night.", "medium", matched=("Medium risk",)),
        ),
        (
            "HIGH RISK. Two unidentified men in hoodies are in the courtyard.",
            Outcome("Two unidentified men in hoodies are in the courtyard.", "high", matched=("High risk",)),
        ),
        (
            "critical risk masked individual moving quickly through the courtyard at night.",
            Outcome("Masked individual moving quickly through the courtyard at night.", "critical", matched=("Critical risk",)),
        ),
        (
            "NO RISK A service worker is walking towards the house.",
            Outcome("NO RISK A service worker is walking towards the house.", silence=True, matched=("No or low risk",)),
        ),
        (
            "LOW RISK. Unidentified vehicle approaching the courtyard.",
            Outcome("LOW RISK. Unidentified vehicle approaching the courtyard.", silence=True, matched=("No or low risk",)),
        ),
        ("UNKNOWN BIRD on the lawn.", Outcome("UNKNOWN BIRD on the lawn.", silence=True, matched=("Unclear",))),
        (
            "BIRD IDENTIFIED blackbird, on the driveway in front of the driveway camera.",
            Outcome("Blackbird, on the driveway in front of the driveway camera.", "minimum", matched=("Birds",)),
        ),
        # names keep their case, unlike the automation's lower-casing
        (
            "MEDIUM RISK. White vehicle in the pend entrance. Matches neighbor Ramzi's car.",
            Outcome("White vehicle in the pend entrance. Matches neighbor Ramzi's car.", "medium", matched=("Medium risk",)),
        ),
        ("Person detected in Barn Door", Outcome("Person detected in Barn Door")),
    ],
)
def test_suggested_rules(description: str, expected: Outcome):
    assert apply_rules(rules(*SUGGESTED), description) == expected


def test_every_match_applies():
    combined = rules(
        {"name": "a", "match": "contains", "pattern": "barn", "priority": "low", "scenarios": ["barn", "noisy"]},
        {"name": "b", "match": "contains", "pattern": "PERSON", "priority": "high", "scenarios": ["noisy", "person"]},
        {"name": "c", "match": "contains", "pattern": "nothing like it", "silence": True},
    )
    assert apply_rules(combined, "Person walks to the barn") == Outcome(
        "Person walks to the barn", "high", scenarios=("barn", "noisy", "person"), matched=("a", "b")
    )


def test_silence_wins():
    combined = rules(
        {"name": "a", "match": "contains", "pattern": "cat", "priority": "critical"},
        {"name": "b", "match": "starts_with", "pattern": "  the", "silence": True},
    )
    outcome = apply_rules(combined, "The cat sat")
    assert outcome.silence
    assert outcome.priority == "critical"


def test_plain_text_not_a_pattern():
    (rule,) = rules({"name": "a", "match": "contains", "pattern": "a.b (c)", "remove": True})
    assert apply_rules([rule], "x a.b (c) y").message == "X y"
    assert apply_rules([rule], "x aXb c y").matched == ()


def test_removing_everything_keeps_message():
    (rule,) = rules({"name": "a", "match": "regex", "pattern": ".*", "remove": True})
    assert apply_rules([rule], "All of it").message == "All of it"


def test_unusable_rules_ignored(caplog: pytest.LogCaptureFixture):
    assert rules({"name": "bad", "match": "regex", "pattern": "(unclosed"}) == []
    assert "Rule bad ignored" in caplog.text
    assert rules({"name": "empty", "match": "contains", "pattern": ""}) == []
    (rule,) = rules({"name": "odd", "pattern": "x", "priority": "urgent"})
    assert rule.priority is None


def test_rank():
    assert rank("critical") > rank("high") > rank("medium") > rank("low") > rank("minimum") > rank(None)
    assert rank("urgent") == rank(None)
