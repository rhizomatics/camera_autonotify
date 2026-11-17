"""The actions on a notification, as buttons on a phone, offered where Frigate can do them, and done when tapped"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.camera_autonotify.actions import EVENT_ACTION, Action, async_act, available, offered
from custom_components.camera_autonotify.const import CONF_ACTIONS, CONF_ACTIONS_GLOBAL, DOMAIN
from custom_components.camera_autonotify.facts import FactStore
from custom_components.camera_autonotify.frigate import fact_stores
from custom_components.camera_autonotify.tracker import Description, Reason, Review
from tests.ha_testing import MockConfigEntry

from .conftest import FRIGATE_ENTRY_ID, add_frigate
from .test_notifier import DETECTION, ENTRY_ID, REVIEW_ID, decision, notifier

FRIGATE_CONFIG: dict[str, Any] = {
    "plus": {"enabled": True},
    "cameras": {"courtyard": {"snapshots": {"enabled": True}, "record": {"enabled": True}}, "driveway": {}},
}


def kinds(actions: list[Action]) -> list[str]:
    return [action.kind for action in actions]


def client(hass: HomeAssistant) -> AsyncMock:
    fake = AsyncMock()
    hass.data["frigate"][FRIGATE_ENTRY_ID]["client"] = fake
    return fake


def global_actions(hass: HomeAssistant, actions: list[str]) -> None:
    MockConfigEntry(domain=DOMAIN, data={"type": "discovery"}, options={CONF_ACTIONS: actions}).add_to_hass(hass)


def test_name_round_trip():
    action = Action("plus", "01ENTRY", "1792602227.86265-dyoaxn")
    assert action.name == "CAMERA_AUTONOTIFY_PLUS|01ENTRY|1792602227.86265-dyoaxn"
    assert Action.parse(action.name) == action


@pytest.mark.parametrize(
    "name",
    [
        None,
        42,
        "SUPERNOTIFY_SNOOZE_EVERYONE",
        "CAMERA_AUTONOTIFY_DELETE|a|b",
        "CAMERA_AUTONOTIFY_KEEP|a",
        "CAMERA_AUTONOTIFY_KEEP||b",
    ],
)
def test_not_ours(name: object):
    assert Action.parse(name) is None


def test_offered_by_what_frigate_can_do():
    assert offered([FRIGATE_CONFIG]) == ["keep", "seen", "plus", "export"]
    # for a camera that neither saves snapshots nor records
    assert offered([FRIGATE_CONFIG], ["driveway"]) == ["keep", "seen"]
    assert offered([{**FRIGATE_CONFIG, "plus": {"enabled": False}}]) == ["keep", "seen", "export"]
    assert offered([None]) == ["keep", "seen"]


async def test_available_as_global_settings(hass: HomeAssistant):
    add_frigate(hass, snapshots=True, plus=True, record=True)
    # keep, seen and Frigate+ to begin with, exporting only when chosen
    assert kinds(available(hass, notifier(hass).entry, decision())) == ["keep", "seen", "plus"]
    global_actions(hass, ["seen", "export"])
    assert kinds(available(hass, notifier(hass).entry, decision())) == ["seen", "export"]


async def test_available_as_camera_chooses(hass: HomeAssistant):
    add_frigate(hass, snapshots=True, plus=True)
    entry = notifier(hass, options={CONF_ACTIONS_GLOBAL: False, CONF_ACTIONS: ["plus", "keep", "export"]}).entry
    # in their own order, and not exporting where the camera doesn't record
    assert kinds(available(hass, entry, decision())) == ["keep", "plus"]
    assert available(hass, notifier(hass, options={CONF_ACTIONS_GLOBAL: False}).entry, decision()) == []


async def test_plus_only_with_a_snapshot(hass: HomeAssistant):
    add_frigate(hass, snapshots=True, plus=True)
    entry = notifier(hass).entry
    assert "plus" in kinds(available(hass, entry, decision()))
    add_frigate(hass, snapshots=False, plus=True)
    assert "plus" not in kinds(available(hass, entry, decision()))


async def test_plus_not_where_frigate_has_no_snapshot(hass: HomeAssistant):
    """As the tracked object says, once it's known"""
    add_frigate(hass, snapshots=True, plus=True)

    store = fact_stores(hass).setdefault("frigate", FactStore())
    store.on_event({"after": {"id": DETECTION, "has_snapshot": False}}, 1.0)
    assert "plus" not in kinds(available(hass, notifier(hass).entry, decision()))


async def test_object_described_by_itself(hass: HomeAssistant):
    """No review to mark as seen or export"""
    add_frigate(hass, snapshots=True, plus=True, record=True)
    global_actions(hass, ["keep", "seen", "plus", "export"])
    found = decision()
    alone = type(found)(Review.of_object(Description("object-1", "courtyard", "A van")), Reason.DESCRIPTION, 0, False)
    assert kinds(available(hass, notifier(hass).entry, alone)) == ["keep", "plus"]


@pytest.mark.parametrize(
    ("kind", "target", "called"),
    [
        ("keep", DETECTION, ("async_retain", (DETECTION, True))),
        ("seen", REVIEW_ID, ("async_set_reviews_viewed", ([REVIEW_ID], True))),
        ("plus", DETECTION, ("api_wrapper", ("post", f"http://frigate:5000/api/events/{DETECTION}/plus"))),
    ],
)
async def test_act(hass: HomeAssistant, kind: str, target: str, called: tuple[str, tuple[Any, ...]]):
    add_frigate(hass)
    notifier(hass)
    fake = client(hass)
    assert await async_act(hass, Action(kind, ENTRY_ID, target))
    getattr(fake, called[0]).assert_awaited_once_with(*called[1])


async def test_export_around_the_review(hass: HomeAssistant):
    add_frigate(hass)
    notifier(hass)
    fake = client(hass)
    started = float(REVIEW_ID.partition("-")[0])
    fake.async_get_reviews.return_value = [
        {"id": "other", "camera": "driveway", "start_time": started},
        {"id": REVIEW_ID, "camera": "courtyard", "start_time": started, "end_time": started + 30},
    ]
    assert await async_act(hass, Action("export", ENTRY_ID, REVIEW_ID))
    assert fake.async_get_reviews.await_args.kwargs == {"after": started - 1, "before": started + 1}
    fake.async_export_recording.assert_awaited_once_with("courtyard", "realtime", started - 10, started + 40)


async def test_export_of_a_review_gone(hass: HomeAssistant):
    add_frigate(hass)
    notifier(hass)
    fake = client(hass)
    fake.async_get_reviews.return_value = []
    assert not await async_act(hass, Action("export", ENTRY_ID, REVIEW_ID))
    assert not await async_act(hass, Action("export", ENTRY_ID, "not-a-time"))
    fake.async_export_recording.assert_not_awaited()


async def test_act_failing(hass: HomeAssistant, caplog: pytest.LogCaptureFixture):
    add_frigate(hass)
    notifier(hass)
    client(hass).async_retain.side_effect = Exception("404")
    assert not await async_act(hass, Action("keep", ENTRY_ID, DETECTION))
    assert f"Frigate couldn't keep {DETECTION}: 404" in caplog.text


async def test_act_without_entry_or_frigate(hass: HomeAssistant):
    assert not await async_act(hass, Action("keep", "nothing", DETECTION))
    notifier(hass)
    assert not await async_act(hass, Action("keep", ENTRY_ID, DETECTION))


async def test_tapped(hass: HomeAssistant):
    """Done when tapped on a phone, as the mobile app's event says, from the integration's setup"""
    add_frigate(hass)
    notifier(hass)
    fake = client(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    hass.bus.async_fire(EVENT_ACTION, {"action": f"CAMERA_AUTONOTIFY_SEEN|{ENTRY_ID}|{REVIEW_ID}"})
    hass.bus.async_fire(EVENT_ACTION, {"action": "SUPERNOTIFY_SNOOZE_EVERYONE"})
    await hass.async_block_till_done()
    fake.async_set_reviews_viewed.assert_awaited_once_with([REVIEW_ID], True)
