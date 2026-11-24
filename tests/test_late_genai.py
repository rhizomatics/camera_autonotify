"""What GenAI adds long after what it describes ended: said how long ago, given a priority of its own, or none, and
Supernotify scenarios, by how late it is from the review's or object's end"""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Any

import pytest
from homeassistant.core import Context, HomeAssistant

from custom_components.camera_autonotify.facts import FactStore
from custom_components.camera_autonotify.frigate import fact_stores
from custom_components.camera_autonotify.texts import async_load_texts
from custom_components.camera_autonotify.tracker import Decision

from .conftest import add_frigate, mock_supernotify
from .test_discovery import set_up_discovery
from .test_notifier import add_rules, described, notifier, summarised
from .test_settings import fields_of, open_settings

MESSAGE = "A person walks to the barn."


def late_summary(seconds: float, level: int = 0) -> Decision:
    decision = summarised(level)
    return replace(decision, review=replace(decision.review, end_time=time.time() - seconds))


async def data(hass: HomeAssistant, decision: Decision, **options: Any) -> dict[str, Any]:
    await async_load_texts(hass)
    return notifier(hass, options=options).supernotify_data(decision)


@pytest.mark.parametrize(
    ("seconds", "message"),
    [
        (60, MESSAGE),
        (130, f"Ended 2 minutes ago: {MESSAGE}"),
        (400, f"Ended 6 minutes ago: {MESSAGE}"),
    ],
)
async def test_said_how_long_ago(hass: HomeAssistant, seconds: float, message: str):
    found = await data(hass, late_summary(seconds))
    assert found["message"] == message
    # for reading, not hearing
    assert "ago" not in found["spoken_message"]
    # nothing else, until chosen
    assert found["priority"] == "low"
    assert "apply_scenarios" not in found


async def test_said_after_chosen(hass: HomeAssistant):
    assert (await data(hass, late_summary(30), late_said_after=20))["message"].startswith("Ended 30 seconds ago")
    assert (await data(hass, late_summary(4000), late_said_after=0))["message"] == MESSAGE


async def test_not_late_without_an_end(hass: HomeAssistant):
    found = await data(hass, summarised(0), late_after=1, late_scenarios=["genai_late"])
    assert found["message"] == MESSAGE
    assert "apply_scenarios" not in found


async def test_late_priority(hass: HomeAssistant):
    options = {"late_priority": "minimum"}
    # lower than an update's own, as chosen
    assert (await data(hass, late_summary(400), **options))["priority"] == "minimum"
    assert (await data(hass, late_summary(100), **options))["priority"] == "low"
    # suspicious and critical keep their own
    assert (await data(hass, late_summary(400, level=1), **options))["priority"] == "high"
    # sounding only above the review's own, as any update
    assert (await data(hass, late_summary(400), late_priority="critical"))["priority"] == "critical"
    assert (await data(hass, late_summary(400), late_priority="high"))["priority"] == "low"
    assert (await data(hass, late_summary(400), late_priority="unchanged"))["priority"] == "low"
    assert (await data(hass, late_summary(400), late_priority="minimum", late_after=0))["priority"] == "low"


async def test_late_scenarios(hass: HomeAssistant):
    add_rules(hass, {"name": "barn", "match": "contains", "pattern": "barn", "scenarios": ["noisy"]})
    options = {"late_scenarios": ["genai_late", "noisy"]}
    assert (await data(hass, late_summary(400), **options))["apply_scenarios"] == ["noisy", "genai_late"]
    assert (await data(hass, late_summary(100), **options))["apply_scenarios"] == ["noisy"]


async def test_late_not_notified(hass: HomeAssistant):
    calls = mock_supernotify(hass)
    found = notifier(hass, options={"late_priority": "none"})
    await found.async_notify(late_summary(400), Context())
    await found.async_notify(late_summary(100), Context())
    assert len(calls) == 1


async def test_late_given_a_priority_by_a_rule_notified(hass: HomeAssistant):
    add_rules(hass, {"name": "barn", "match": "contains", "pattern": "barn", "priority": "high"})
    calls = mock_supernotify(hass)
    await notifier(hass, options={"late_priority": "none"}).async_notify(late_summary(400), Context())
    assert len(calls) == 1


async def test_description_late_by_its_object(hass: HomeAssistant):
    add_frigate(hass)
    store = fact_stores(hass).setdefault("frigate", FactStore())
    ended = time.time() - 400
    store.on_event({"type": "end", "after": {"id": "object-1", "camera": "courtyard", "end_time": ended}}, ended)
    found = await data(hass, described("A van parks."), late_priority="minimum")
    assert found["message"] == "Ended 6 minutes ago: A van parks."
    assert found["priority"] == "minimum"
    # not yet ended, so not late
    store.on_event({"type": "update", "after": {"id": "object-2", "camera": "courtyard"}}, ended)
    on_time = replace(described("A van parks."), described_id="object-2")
    assert (await data(hass, on_time))["message"] == "A van parks."


async def test_new_never_late(hass: HomeAssistant):
    decision = late_summary(400)
    found = await data(hass, replace(decision, reason=type(decision.reason).NEW), late_priority="none")
    assert "ago" not in found["message"]


async def test_late_scenarios_offered_with_supernotify(hass: HomeAssistant):
    add_frigate(hass, genai=True)
    mock_supernotify(hass)
    await set_up_discovery(hass)
    assert "genai.late_scenarios" in fields_of(await open_settings(hass))
