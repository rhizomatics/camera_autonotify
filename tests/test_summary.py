from __future__ import annotations

from datetime import date, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_TYPE
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.util import dt as dt_util

from custom_components.camera_autonotify.const import (
    CONF_AUTO_DISCOVER,
    CONF_DISCOVER_ZONES,
    CONF_SUMMARY_CONCERNS,
    CONF_SUMMARY_DELIVERIES,
    CONF_SUMMARY_INTERVAL,
    CONF_SUMMARY_MODE,
    CONF_SUMMARY_TIME,
    DISCOVERY_TITLE,
    DOMAIN,
    TYPE_DISCOVERY,
)
from custom_components.camera_autonotify.frigate import concerning
from custom_components.camera_autonotify.summary import SummarySettings, said_day, said_period, summary_text
from tests.ha_testing import MockConfigEntry, async_fire_time_changed, async_mock_service

from .conftest import FRIGATE_ENTRY_ID, FakeMQTT, add_frigate, mock_supernotify
from .test_discovery import set_up_discovery
from .test_tracker import message, review

SUMMARY = "A quiet day: the post came at 10:12, and a fox crossed the drive at 23:40."


def loaded_frigate(hass: HomeAssistant, genai: bool = True, **kwargs: Any) -> AsyncMock:
    """A Frigate server set up, making review summaries or not, with its API client"""
    frigate = add_frigate(hass, genai=genai, **kwargs)
    frigate.entry.mock_state(hass, ConfigEntryState.LOADED)
    client = AsyncMock()
    client.async_review_summarize.return_value = {"success": True, "summary": SUMMARY}
    hass.data["frigate"][frigate.entry.entry_id]["client"] = client
    return client


async def set_up(hass: HomeAssistant, **options: Any) -> config_entries.ConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=DISCOVERY_TITLE,
        data={CONF_TYPE: TYPE_DISCOVERY},
        options={CONF_AUTO_DISCOVER: False, **options},
        unique_id=TYPE_DISCOVERY,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def at(hass: HomeAssistant, freezer: FrozenDateTimeFactory, when: str) -> None:
    freezer.move_to(datetime.fromisoformat(when).replace(tzinfo=dt_util.get_default_time_zone()))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


@pytest.fixture(autouse=True)
async def london(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    await hass.config.async_set_time_zone("Europe/London")
    freezer.move_to(datetime(2026, 11, 10, 23, 30, tzinfo=dt_util.get_default_time_zone()))


async def test_summary_of_the_day_before(hass: HomeAssistant, freezer: FrozenDateTimeFactory):
    client = loaded_frigate(hass)
    calls = mock_supernotify(hass)
    await set_up(hass)
    await at(hass, freezer, "2026-11-11 00:04:59")
    assert calls == []
    await at(hass, freezer, "2026-11-11 00:05:00")

    # the whole of the day before, by Home Assistant's time zone
    start, end = client.async_review_summarize.await_args.args
    assert dt_util.as_local(dt_util.utc_from_timestamp(start)).isoformat() == "2026-11-10T00:00:00+00:00"
    assert dt_util.as_local(dt_util.utc_from_timestamp(end)).isoformat() == "2026-11-11T00:00:00+00:00"
    assert len(calls) == 1
    assert calls[0].data["title"] == "Frigate summary for Tuesday 10 November"
    assert calls[0].data["message"] == SUMMARY
    # by e-mail, too long for a phone or a voice assistant
    assert calls[0].data["delivery"] == ["email"]
    assert calls[0].data["delivery_selection"] == "explicit"

    # once a day
    await at(hass, freezer, "2026-11-11 12:00:00")
    assert len(calls) == 1


async def test_summary_at_time_set(hass: HomeAssistant, freezer: FrozenDateTimeFactory):
    loaded_frigate(hass)
    calls = mock_supernotify(hass)
    await set_up(hass, **{CONF_SUMMARY_TIME: "08:30:00"})
    await at(hass, freezer, "2026-11-11 00:05:00")
    assert calls == []
    await at(hass, freezer, "2026-11-11 08:30:00")
    # the 24 hours before, up to the hour
    assert [call.data["title"] for call in calls] == [
        "Frigate summary for Tuesday 10 November 08:00 to Wednesday 11 November 08:00"
    ]


async def test_no_summary_without_genai(hass: HomeAssistant, freezer: FrozenDateTimeFactory):
    client = loaded_frigate(hass, genai=False)
    calls = mock_supernotify(hass)
    await set_up(hass)
    await at(hass, freezer, "2026-11-11 00:05:00")
    assert calls == []
    assert client.async_review_summarize.await_count == 0


async def test_summary_once_genai_review_seen(hass: HomeAssistant, freezer: FrozenDateTimeFactory, fake_mqtt: FakeMQTT):
    """Frigate's config not saying it makes summaries, but one having come over MQTT on the day summarised"""
    loaded_frigate(hass, genai=False)
    calls = mock_supernotify(hass)
    await set_up_discovery(hass)
    fake_mqtt.publish("frigate/reviews", message("genai", review("courtyard")))
    await hass.async_block_till_done()
    calls.clear()
    await at(hass, freezer, "2026-11-11 00:05:00")
    assert [call.data["title"] for call in calls] == ["Frigate summary for Tuesday 10 November"]

    # none on the day after, so no summary of it
    calls.clear()
    await at(hass, freezer, "2026-11-12 00:05:00")
    assert calls == []


@pytest.mark.parametrize(("mode", "genai", "sent"), [("on", False, True), ("off", True, False)])
async def test_summary_switched(hass: HomeAssistant, freezer: FrozenDateTimeFactory, mode: str, genai: bool, sent: bool):
    loaded_frigate(hass, genai=genai)
    calls = mock_supernotify(hass)
    await set_up(hass, **{CONF_SUMMARY_MODE: mode})
    await at(hass, freezer, "2026-11-11 00:05:00")
    assert len(calls) == int(sent)


async def test_summary_failure_logged(hass: HomeAssistant, freezer: FrozenDateTimeFactory, caplog: pytest.LogCaptureFixture):
    client = loaded_frigate(hass)
    client.async_review_summarize.side_effect = Exception("429 RESOURCE_EXHAUSTED")
    calls = mock_supernotify(hass)
    await set_up(hass)
    await at(hass, freezer, "2026-11-11 00:05:00")
    assert calls == []
    assert "Frigate frigate:5000 couldn't summarise Tuesday 10 November: 429 RESOURCE_EXHAUSTED" in caplog.text


async def test_summary_without_frigate_support(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, caplog: pytest.LogCaptureFixture
):
    loaded_frigate(hass)
    hass.data["frigate"][FRIGATE_ENTRY_ID]["client"] = object()
    calls = mock_supernotify(hass)
    await set_up(hass)
    await at(hass, freezer, "2026-11-11 00:05:00")
    assert calls == []
    assert "needing Frigate 0.17" in caplog.text


async def test_summary_from_each_server(hass: HomeAssistant, freezer: FrozenDateTimeFactory):
    loaded_frigate(hass)
    loaded_frigate(hass, entry_id="frigate_garden", client_id="garden", title="garden:5000")
    calls = mock_supernotify(hass)
    await set_up(hass)
    await at(hass, freezer, "2026-11-11 00:05:00")
    assert sorted(call.data["title"] for call in calls) == [
        "Frigate summary for Tuesday 10 November from frigate:5000",
        "Frigate summary for Tuesday 10 November from garden:5000",
    ]
    assert len({call.data["extra_data"]["mobile_push_notification_tag"] for call in calls}) == 2


async def test_summary_in_global_options(hass: HomeAssistant):
    mock_supernotify(hass)
    entry = await set_up(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["data_schema"] is not None
    summary = next(field for key, field in result["data_schema"].schema.items() if str(key) == "summary")
    suggested = {str(key): (key.description or {}).get("suggested_value") for key in summary.schema.schema}
    # Supernotify's e-mail deliveries to begin with
    assert suggested[CONF_SUMMARY_DELIVERIES] == ["email"]
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_AUTO_DISCOVER: False,
            CONF_DISCOVER_ZONES: False,
            "health": {},
            "summary": {
                CONF_SUMMARY_MODE: "on",
                CONF_SUMMARY_INTERVAL: "4",
                CONF_SUMMARY_TIME: "08:30:00",
                CONF_SUMMARY_CONCERNS: True,
                CONF_SUMMARY_DELIVERIES: ["phones"],
            },
        },
    )
    await hass.async_block_till_done()
    assert SummarySettings.from_options(entry.options) == SummarySettings(
        mode="on", at=datetime(2026, 1, 1, 8, 30).time(), interval=4, concerns_only=True, deliveries=("phones",)
    )


async def test_summary_deliveries_cleared(hass: HomeAssistant):
    mock_supernotify(hass)
    entry = await set_up(hass, **{CONF_SUMMARY_DELIVERIES: ["phones"]})
    result = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_AUTO_DISCOVER: False, CONF_DISCOVER_ZONES: False, "health": {}, "summary": {CONF_SUMMARY_MODE: "auto"}},
    )
    await hass.async_block_till_done()
    assert CONF_SUMMARY_DELIVERIES not in entry.options


def test_settings_from_odd_options():
    assert (
        SummarySettings.from_options({
            CONF_SUMMARY_MODE: "sometimes",
            CONF_SUMMARY_TIME: "noon",
            CONF_SUMMARY_INTERVAL: "5",
        })
        == SummarySettings()
    )
    assert SummarySettings.from_options({CONF_SUMMARY_INTERVAL: "often"}) == SummarySettings()


def test_summary_text():
    assert summary_text({"summary": f" {SUMMARY}\n"}) == SUMMARY
    assert summary_text({"summary": " "}) is None
    assert summary_text({"success": False, "message": "Failed to create summary."}) is None
    assert summary_text("Internal Server Error") is None


def test_said_day():
    assert said_day(date(2026, 11, 1)) == "Sunday 1 November"


@pytest.mark.parametrize(
    ("start", "end", "said"),
    [
        ("2026-11-10 00:00", "2026-11-11 00:00", "Tuesday 10 November"),
        ("2026-11-11 08:00", "2026-11-11 12:00", "Wednesday 11 November, 08:00 to 12:00"),
        ("2026-11-10 20:00", "2026-11-11 00:00", "Tuesday 10 November, 20:00 to midnight"),
        ("2026-11-10 22:00", "2026-11-11 02:00", "Tuesday 10 November 22:00 to Wednesday 11 November 02:00"),
    ],
)
def test_said_period(start: str, end: str, said: str):
    assert said_period(datetime.fromisoformat(start), datetime.fromisoformat(end)) == said


def concern(start: str, level: int = 0, other: list[str] | None = None) -> dict[str, Any]:
    started = datetime.fromisoformat(start).replace(tzinfo=dt_util.get_default_time_zone()).timestamp()
    return {
        "id": start,
        "camera": "courtyard",
        "start_time": started,
        "data": {"metadata": {"title": "Person at the door", "potential_threat_level": level, "other_concerns": other}},
    }


async def test_summary_every_few_hours(hass: HomeAssistant, freezer: FrozenDateTimeFactory):
    client = loaded_frigate(hass)
    calls = mock_supernotify(hass)
    await set_up(hass, **{CONF_SUMMARY_INTERVAL: "4", CONF_SUMMARY_TIME: "08:15:00"})
    for hour in range(24):
        await at(hass, freezer, f"2026-11-11 {hour:02}:15:00")
    # every 4 hours from 08:15, the day through
    assert [call.data["title"] for call in calls] == [
        "Frigate summary for Tuesday 10 November, 20:00 to midnight",
        "Frigate summary for Wednesday 11 November, 00:00 to 04:00",
        "Frigate summary for Wednesday 11 November, 04:00 to 08:00",
        "Frigate summary for Wednesday 11 November, 08:00 to 12:00",
        "Frigate summary for Wednesday 11 November, 12:00 to 16:00",
        "Frigate summary for Wednesday 11 November, 16:00 to 20:00",
    ]
    assert client.async_review_summarize.await_count == 6


async def test_summary_only_with_concerns(hass: HomeAssistant, freezer: FrozenDateTimeFactory):
    client = loaded_frigate(hass)
    calls = mock_supernotify(hass)
    await set_up(hass, **{CONF_SUMMARY_INTERVAL: "4", CONF_SUMMARY_TIME: "00:05:00", CONF_SUMMARY_CONCERNS: True})

    # nothing worrying, and one before the hours summarised, so no summary asked for, and no tokens spent
    client.async_get_reviews.return_value = [concern("2026-11-11 05:00"), concern("2026-11-11 03:00", level=1)]
    await at(hass, freezer, "2026-11-11 08:05:00")
    assert calls == []
    assert client.async_review_summarize.await_count == 0
    after, before = (client.async_get_reviews.await_args.kwargs[key] for key in ("after", "before"))
    assert before - after == 4 * 3600

    # a threat level
    client.async_get_reviews.return_value = [concern("2026-11-11 09:00"), concern("2026-11-11 10:30", level=1)]
    await at(hass, freezer, "2026-11-11 12:05:00")
    assert [call.data["title"] for call in calls] == ["Frigate summary for Wednesday 11 November, 08:00 to 12:00"]

    # or other concerns
    client.async_get_reviews.return_value = [concern("2026-11-11 13:00", other=["Gate left open"])]
    await at(hass, freezer, "2026-11-11 16:05:00")
    assert len(calls) == 2


async def test_no_summary_when_reviews_fail(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, caplog: pytest.LogCaptureFixture
):
    client = loaded_frigate(hass)
    client.async_get_reviews.side_effect = Exception("Connection refused")
    calls = mock_supernotify(hass)
    await set_up(hass, **{CONF_SUMMARY_CONCERNS: True})
    await at(hass, freezer, "2026-11-11 00:05:00")
    assert calls == []
    assert "Frigate frigate:5000 couldn't give its reviews: Connection refused" in caplog.text


async def test_no_summary_made_logged(hass: HomeAssistant, freezer: FrozenDateTimeFactory, caplog: pytest.LogCaptureFixture):
    client = loaded_frigate(hass)
    client.async_review_summarize.return_value = {"success": False, "message": "Failed to create summary."}
    calls = mock_supernotify(hass)
    await set_up(hass)
    await at(hass, freezer, "2026-11-11 00:05:00")
    assert calls == []
    assert "made no summary of Tuesday 10 November" in caplog.text


async def test_summary_by_deliveries_chosen(hass: HomeAssistant, freezer: FrozenDateTimeFactory):
    loaded_frigate(hass)
    calls = mock_supernotify(hass)
    await set_up(hass, **{CONF_SUMMARY_DELIVERIES: ["telegram"]})
    await at(hass, freezer, "2026-11-11 00:05:00")
    assert calls[0].data["delivery"] == ["telegram"]


async def test_no_summary_without_supernotify(hass: HomeAssistant, freezer: FrozenDateTimeFactory):
    client = loaded_frigate(hass)
    phones = async_mock_service(hass, "notify", "send_message")
    entry = await set_up(hass, **{CONF_SUMMARY_MODE: "on"})
    await at(hass, freezer, "2026-11-11 00:05:00")
    assert phones == []
    assert client.async_review_summarize.await_count == 0
    # nor offered, only said to need Supernotify
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["data_schema"] is not None
    sections = {str(key): field for key, field in result["data_schema"].schema.items()}
    assert "summary" not in sections
    assert sections["summary_unavailable"].schema.schema == {}
    # whether the empty section comes back or not
    shown: tuple[dict[str, Any], ...] = ({"summary_unavailable": {}}, {})
    for summary in shown:
        result = await hass.config_entries.options.async_init(entry.entry_id)
        await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_AUTO_DISCOVER: False, CONF_DISCOVER_ZONES: False, "health": {}, **summary}
        )
        await hass.async_block_till_done()
        assert dict(entry.options)[CONF_SUMMARY_MODE] == "on"


async def test_no_summary_without_email(hass: HomeAssistant, freezer: FrozenDateTimeFactory, caplog: pytest.LogCaptureFixture):
    client = loaded_frigate(hass)
    calls = mock_supernotify(hass)
    async_mock_service(
        hass,
        "supernotify",
        "enquire_implicit_deliveries",
        response={"mobile_push": ["mobile_push"]},
        supports_response=SupportsResponse.ONLY,
    )
    await set_up(hass)
    await at(hass, freezer, "2026-11-11 00:05:00")
    assert calls == []
    assert client.async_review_summarize.await_count == 0
    assert "Supernotify having no e-mail delivery and none chosen" in caplog.text


def test_concerning():
    assert not concerning({"data": {"metadata": {"potential_threat_level": "unsure"}}})
    assert not concerning({"data": {}})
    assert concerning({"data": {"metadata": {"potential_threat_level": 2}}})
