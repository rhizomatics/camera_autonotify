"""Rules that change how a notification is sent, by what its message says, for any source

Pure logic, with no Home Assistant in it. Every rule that matches applies, so their order doesn't matter: silence
wins, then the most urgent priority, and the scenarios of all of them are combined.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .const import (
    CONF_MATCH,
    CONF_PATTERN,
    CONF_PRIORITY,
    CONF_REMOVE,
    CONF_SCENARIOS,
    CONF_SILENCE,
    MATCH_CONTAINS,
    MATCH_REGEX,
    MATCH_STARTS_WITH,
    PRIORITIES,
)

_LOGGER = logging.getLogger(__name__)

# what's left at the start once text is removed from it, such as the `. ` of `MEDIUM RISK. A person...`
_LEADING = re.compile(r"^[\s\W_]+")
_SPACES = re.compile(r"\s{2,}")


def rank(priority: str | None) -> int:
    """How urgent a priority is, higher for more, and lowest for none or one not known"""
    return len(PRIORITIES) - PRIORITIES.index(priority) if priority in PRIORITIES else 0


def compile_pattern(match: str, pattern: str) -> re.Pattern[str]:
    """A rule's pattern, case-insensitive, raising `re.error` for a regular expression that isn't one"""
    if match == MATCH_REGEX:
        return re.compile(pattern, re.IGNORECASE)
    escaped = re.escape(pattern.strip())
    return re.compile(f"^\\s*{escaped}" if match == MATCH_STARTS_WITH else escaped, re.IGNORECASE)


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern[str]
    priority: str | None = None
    silence: bool = False
    scenarios: tuple[str, ...] = ()
    remove: bool = False

    @classmethod
    def from_data(cls, name: str, data: Mapping[str, Any]) -> Rule | None:
        """From a rule's subentry, or nothing for one that can't be used, with a warning"""
        try:
            pattern = compile_pattern(data.get(CONF_MATCH, MATCH_CONTAINS), data.get(CONF_PATTERN) or "")
        except re.error as error:
            _LOGGER.warning("CAMERA_AUTONOTIFY Rule %s ignored, its pattern isn't a regular expression: %s", name, error)
            return None
        if not pattern.pattern:
            return None
        priority = data.get(CONF_PRIORITY)
        return cls(
            name=name,
            pattern=pattern,
            priority=priority if priority in PRIORITIES else None,
            silence=bool(data.get(CONF_SILENCE, False)),
            scenarios=tuple(data.get(CONF_SCENARIOS) or ()),
            remove=bool(data.get(CONF_REMOVE, False)),
        )


@dataclass(frozen=True)
class Outcome:
    """What the rules that matched make of a message"""

    message: str
    priority: str | None = None
    silence: bool = False
    scenarios: tuple[str, ...] = ()
    matched: tuple[str, ...] = ()


def _tidy(message: str) -> str:
    message = _SPACES.sub(" ", _LEADING.sub("", message)).strip()
    return message[:1].upper() + message[1:]


def apply_rules(rules: Iterable[Rule], message: str) -> Outcome:
    priority: str | None = None
    silence = False
    scenarios: list[str] = []
    matched: list[str] = []
    text = message
    for rule in rules:
        found = rule.pattern.search(message)
        if found is None:
            continue
        matched.append(rule.name)
        silence = silence or rule.silence
        if rank(rule.priority) > rank(priority):
            priority = rule.priority
        scenarios.extend(scenario for scenario in rule.scenarios if scenario not in scenarios)
        if rule.remove and found.group(0):
            # each match is removed from the message as it now is, so rules can each take their own part
            text = text.replace(found.group(0), " ", 1)
    if text != message:
        text = _tidy(text)
    return Outcome(text or message, priority, silence, tuple(scenarios), tuple(matched))
