"""Importing from anpr2mqtt, from an archive of its config and data folders, uploaded in Global Settings or as an
anpr2mqtt source is set up"""

from __future__ import annotations

import io
import json
import tarfile
from collections.abc import Mapping
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
import yaml
from homeassistant import config_entries
from homeassistant.const import CONF_DEVICE_ID, CONF_NAME, CONF_TYPE
from homeassistant.data_entry_flow import FlowResultType

from custom_components.camera_autonotify.const import (
    CONF_SOURCE,
    CONF_SOURCE_ENTRY_ID,
    CONF_SOURCE_NAME,
    DOMAIN,
    TYPE_ANPR,
    TYPE_DISCOVERY,
)
from custom_components.camera_autonotify.migrate import ArchiveUnreadable, from_anpr2mqtt, read_archive
from custom_components.camera_autonotify.vehicles import vehicles

from .conftest import add_frigate
from .test_discovery import set_up_discovery
from .test_vehicles import ANPR2MQTT_CONFIG, global_settings

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from homeassistant.core import HomeAssistant

# upload ids, as the file upload integration makes them
UPLOAD = "0b2a6f1c-6a1d-4d3e-9a51-3f1e2b9c8d70"
GONE = "5c3e7a9b-1f2d-4c6e-8b0a-9d7f6e5c4b3a"
SEEN = ["2026-11-09T14:25:03+00:00", "2026-11-10T08:01:00"]


def test_from_anpr2mqtt():
    found = from_anpr2mqtt(yaml.safe_load(ANPR2MQTT_CONFIG))
    assert set(found.categories) == {"known", "Amazon Prime", "dangerous", "Ignored reads"}
    assert found.categories["known"]["plates"] == [
        {"plate": "TJ912UKL", "description": "joe's mini conv", "corrections": ["J912UKL"]},
        {"plate": "P001PAT", "corrections": ["P0O1PAT"]},
    ]
    assert found.categories["dangerous"]["kind"] == "dangerous"
    assert found.categories["Amazon Prime"]["icon"] == "mdi:truck-delivery"
    assert found.categories["Ignored reads"] == {"kind": "known", "ignore": True, "plates": [{"plate": "^I\\dZ$"}]}
    assert found.settings == {"dvla_api_key": "placeholder", "lookup_cache_hours": 2, "min_visit_gap": 60}
    assert found.not_imported == [
        "priority critical of dangerous, set by the vehicle rules instead",
        "corrections for UN001TST, as they're in no category. Add them to one to correct them",
    ]


def test_from_anpr2mqtt_older_style():
    # a group with no name left out
    found = from_anpr2mqtt({"targets": {"plate": {"known": {"AB12CDE": "Our car"}, "groups": [{"members": ["X"]}]}}})
    assert list(found.categories) == ["known"]
    assert found.categories["known"]["plates"] == [{"plate": "AB12CDE", "description": "Our car"}]


def test_from_anpr2mqtt_older_style_details():
    """A plate's mapping of description and `entity_id`, the sensors of which there are none here, and corrections
    the same as a plate's own taken once"""
    found = from_anpr2mqtt({
        "targets": {
            "plate": {
                "known": {"MY13CAR": {"entity_id": "my_truck", "description": "Ramzi's Land Rover"}, "AB12CDE": None},
                "groups": [{"name": "Vans", "entity_id": "vans", "members": [{"id": "VN01VAN", "correction": ["VN0IVAN"]}]}],
                "correction": {"VN01VAN": ["VN0IVAN", "VNO1VAN"], "LD71HVF": ["D71HVF"], "XX11XXX": ["X11XXX"]},
            }
        }
    })
    assert found.categories["known"]["plates"] == [
        {"plate": "MY13CAR", "description": "Ramzi's Land Rover"},
        {"plate": "AB12CDE"},
    ]
    assert "entity_id" not in found.categories["Vans"]
    assert found.categories["Vans"]["plates"][0]["corrections"] == ["VN0IVAN", "VNO1VAN"]
    assert found.not_imported == [
        "entity_id of Vans, MY13CAR, as there's no sensor for each vehicle here",
        "corrections for LD71HVF, XX11XXX, as they're in no category. Add them to one to correct them",
    ]


def archive(folder: Path, files: Mapping[str, str | bytes], name: str = "anpr2mqtt.tgz") -> Path:
    path = folder / name
    with tarfile.open(path, "w:gz") as tar:
        for member, content in files.items():
            data = content if isinstance(content, bytes) else content.encode()
            info = tarfile.TarInfo(member)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        # folders, read past
        folder_info = tarfile.TarInfo("anpr2mqtt/data/plate")
        folder_info.type = tarfile.DIRTYPE
        tar.addfile(folder_info)
    return path


ANPR2MQTT_FILES = {
    "anpr2mqtt/config/anpr2mqtt.yaml": ANPR2MQTT_CONFIG,
    "anpr2mqtt/data/plate/PX19TVD.json": json.dumps(SEEN),
    "anpr2mqtt/data/plate/broken.json": "not json",
    "anpr2mqtt/data/cache/PX19TVD.json": "{}",
}


def test_read_archive(tmp_path: Path):
    found = read_archive(archive(tmp_path, ANPR2MQTT_FILES))
    assert set(found.categories) == {"known", "Amazon Prime", "dangerous", "Ignored reads"}
    # the tracker's plates only, not the DVLA's cache
    assert found.history == {"PX19TVD": SEEN}


def test_archive_of_config_and_flat_data(tmp_path: Path):
    """The older config name, and the plates' files in the data folder itself, the unread plates' file skipped"""
    found = read_archive(
        archive(
            tmp_path,
            {
                "config/config.yaml": ANPR2MQTT_CONFIG,
                "data/PX19TVD.json": json.dumps(SEEN),
                "data/UNKNOWN.json": json.dumps(SEEN),
                "data/plate/sk43kjf.json": json.dumps(SEEN),
                "data/plate/._sk43kjf.json": b"\x00\x05\x16\x07\xa3",
                "data/plate/binary.json": b"\xa3\xff",
            },
        )
    )
    assert "known" in found.categories
    assert sorted(found.history) == ["PX19TVD", "SK43KJF"]


@pytest.mark.parametrize(
    "files", [{"data/plate/PX19TVD.json": "[]"}, {"config/config.yaml": "- a list"}, {"config/config.yaml": "a: [b"}]
)
def test_archive_without_config(tmp_path: Path, files: dict[str, str]):
    with pytest.raises(ArchiveUnreadable):
        read_archive(archive(tmp_path, files))


def test_not_an_archive(tmp_path: Path):
    path = tmp_path / "anpr2mqtt.tgz"
    path.write_text("not an archive")
    with pytest.raises(ArchiveUnreadable):
        read_archive(path)


@contextmanager
def uploaded(uploads: dict[str, Path]) -> Generator[None]:
    """The file upload integration, with each upload's id as the archive, gone once read as an upload is"""

    @contextmanager
    def process(hass: HomeAssistant, file_id: str) -> Generator[Path]:
        if file_id not in uploads:
            raise ValueError("File does not exist")
        yield uploads.pop(file_id)

    with patch("custom_components.camera_autonotify.config_flow.process_uploaded_file", process):
        yield


async def global_settings_form(hass: HomeAssistant, archive_id: str) -> dict[str, Any]:
    add_frigate(hass)
    await set_up_discovery(hass)
    entry = next(e for e in hass.config_entries.async_entries(DOMAIN) if e.data.get(CONF_TYPE) == TYPE_DISCOVERY)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    return dict(
        await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                "auto_discover": True,
                "discover_zones": False,
                "health": {},
                "vehicles": {"min_visit_gap": 300},
                "anpr2mqtt_import": {"anpr2mqtt_archive": archive_id},
            },
        )
    )


async def test_import_in_global_settings(hass: HomeAssistant, tmp_path: Path):
    with uploaded({UPLOAD: archive(tmp_path, ANPR2MQTT_FILES)}):
        shown = await global_settings_form(hass, UPLOAD)
    assert shown["step_id"] == "import_anpr2mqtt"
    found = shown["description_placeholders"]["found"]
    assert "- Plates in known: 2" in found
    assert "- Visit history: 1 plates, 2 sightings" in found
    assert "DVLA API key" in found
    assert "Not imported: corrections for UN001TST, as they're in no category" in found
    entry = next(e for e in hass.config_entries.async_entries(DOMAIN) if e.data.get(CONF_TYPE) == TYPE_DISCOVERY)
    # nothing until confirmed
    assert not entry.subentries

    done = await hass.config_entries.options.async_configure(shown["flow_id"], {})
    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert done["description"] == "anpr2mqtt_imported"
    imported = (done["description_placeholders"] or {})["imported"]
    assert "- New categories: 4" in imported
    assert "- Sightings added: 2" in imported
    assert "DVLA API key" in imported
    await hass.async_block_till_done()
    assert sorted(s.title for s in entry.subentries.values()) == ["Amazon Prime", "Ignored reads", "dangerous", "known"]
    # the anpr2mqtt gap, over the form's own, and its key a credential
    assert entry.options["min_visit_gap"] == 60
    assert entry.options["auto_discover"] is True
    assert entry.data["dvla_api_key"] == "placeholder"
    assert "dvla_api_key" not in entry.options
    assert len(vehicles(hass).sightings("PX19TVD")) == 2


async def test_import_adds_only_new_plates(hass: HomeAssistant, tmp_path: Path):
    entry = global_settings(hass, {"known": {"plates": [{"plate": "TJ912UKL"}]}})
    from custom_components.camera_autonotify.migrate import async_import, new_plates

    found = read_archive(archive(tmp_path, ANPR2MQTT_FILES))
    assert new_plates(entry, found)["known"] == (1, True)
    added = await async_import(hass, entry, found)
    assert (added.categories, added.sightings) == (3, 2)
    known = next(s for s in entry.subentries.values() if s.title == "known")
    assert [p["plate"] for p in known.data["plates"]] == ["TJ912UKL", "P001PAT"]
    # again, adding nothing
    added = await async_import(hass, entry, found)
    assert (added.categories, added.plates, added.sightings) == (0, 0, 0)
    assert all(count == 0 for count, _ in new_plates(entry, found).values())


async def test_unreadable_archive_in_global_settings(hass: HomeAssistant, tmp_path: Path):
    bad = tmp_path / "bad.tgz"
    bad.write_text("not an archive")
    with uploaded({UPLOAD: bad}):
        shown = await global_settings_form(hass, UPLOAD)
    assert shown["step_id"] == "discovery"
    assert shown["errors"] == {"base": "archive_unreadable"}
    # an upload gone, as after a restart
    with uploaded({}):
        result = await hass.config_entries.options.async_configure(
            shown["flow_id"],
            {"auto_discover": True, "discover_zones": False, "health": {}, "anpr2mqtt_import": {"anpr2mqtt_archive": GONE}},
        )
    assert result["errors"] == {"base": "archive_unreadable"}


def anpr_found() -> dict[str, Any]:
    return {
        CONF_DEVICE_ID: "anpr_device",
        CONF_NAME: "Driveway ANPR",
        CONF_TYPE: TYPE_ANPR,
        CONF_SOURCE: "anpr2mqtt",
        CONF_SOURCE_ENTRY_ID: "01MQTT",
        CONF_SOURCE_NAME: "sensor.anpr_driveway",
    }


async def offered_anpr(hass: HomeAssistant) -> dict[str, Any]:
    return dict(
        await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_INTEGRATION_DISCOVERY}, data=anpr_found()
        )
    )


async def test_import_as_anpr2mqtt_is_set_up(hass: HomeAssistant, tmp_path: Path):
    entry = global_settings(hass)
    shown = await offered_anpr(hass)
    assert shown["step_id"] == "confirm_anpr"
    assert "anpr2mqtt_archive" in shown["data_schema"].schema
    with uploaded({UPLOAD: archive(tmp_path, ANPR2MQTT_FILES)}):
        found = await hass.config_entries.flow.async_configure(shown["flow_id"], {"anpr2mqtt_archive": UPLOAD})
    assert found["step_id"] == "import_anpr2mqtt"
    done = await hass.config_entries.flow.async_configure(shown["flow_id"], {})
    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert done["title"] == "Driveway ANPR"
    assert "- New categories: 4" in (done["description_placeholders"] or {})["imported"]
    assert len(entry.subentries) == 4
    assert entry.data["dvla_api_key"] == "placeholder"
    assert entry.options["min_visit_gap"] == 60


async def test_anpr2mqtt_set_up_without_import(hass: HomeAssistant, tmp_path: Path):
    global_settings(hass)
    shown = await offered_anpr(hass)
    bad = tmp_path / "bad.tgz"
    bad.write_text("not an archive")
    with uploaded({UPLOAD: bad}):
        retry = await hass.config_entries.flow.async_configure(shown["flow_id"], {"anpr2mqtt_archive": UPLOAD})
    assert retry["errors"] == {"base": "archive_unreadable"}
    done = await hass.config_entries.flow.async_configure(shown["flow_id"], {})
    assert done["type"] is FlowResultType.CREATE_ENTRY


async def test_no_import_once_categories(hass: HomeAssistant):
    global_settings(hass, {"known": {"plates": [{"plate": "TJ912UKL"}]}})
    shown = await offered_anpr(hass)
    assert shown["data_schema"].schema == {}


async def test_import_needs_global_settings(hass: HomeAssistant, tmp_path: Path):
    entry = global_settings(hass)
    shown = await offered_anpr(hass)
    with uploaded({UPLOAD: archive(tmp_path, ANPR2MQTT_FILES)}):
        await hass.config_entries.flow.async_configure(shown["flow_id"], {"anpr2mqtt_archive": UPLOAD})
    await hass.config_entries.async_remove(entry.entry_id)
    result = await hass.config_entries.flow.async_configure(shown["flow_id"], {})
    assert result["reason"] == "global_settings_missing"
