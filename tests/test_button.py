"""Test the Generac button platform."""
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from custom_components.generac import button as button_platform
from custom_components.generac.auth import DPoPKey
from custom_components.generac.button import OutageBoostButton
from custom_components.generac.const import CONF_DPOP_PEM
from custom_components.generac.const import CONF_REFRESH_TOKEN
from custom_components.generac.const import CONF_USERNAME
from custom_components.generac.const import DEVICE_TYPE_GENERATOR
from custom_components.generac.const import DEVICE_TYPE_PROPANE_MONITOR
from custom_components.generac.const import DOMAIN
from custom_components.generac.coordinator import GeneracDataUpdateCoordinator
from custom_components.generac.models import Apparatus
from custom_components.generac.models import ApparatusDetail
from custom_components.generac.models import Item
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry


def _make_item(device_type: int, name: str = "Generator") -> Item:
    """Build a minimal Item for button platform tests."""
    return Item(
        apparatus=Apparatus(apparatusId=12345, name=name, type=device_type),
        apparatusDetail=ApparatusDetail(apparatusId=12345, name=name),
    )


async def test_outage_boost_button_metadata_and_press(hass: HomeAssistant) -> None:
    """OutageBoostButton exposes expected attributes and triggers boost on press."""
    coordinator = MagicMock()
    coordinator.async_trigger_boost = AsyncMock()
    entry = MagicMock()
    entry.entry_id = "entry1"
    item = _make_item(DEVICE_TYPE_GENERATOR)

    btn = OutageBoostButton(coordinator, entry, "12345", item)
    assert btn.entity_key == "boost_polling"
    assert btn.name == "Outage Boost Poll"
    assert btn.icon == "mdi:lightning-bolt-circle"
    assert btn.unique_id == "entry1_12345_generac_12345_boost_polling"

    await btn.async_press()
    coordinator.async_trigger_boost.assert_awaited_once_with()


async def test_button_setup_creates_only_generator_entities(
    hass: HomeAssistant,
) -> None:
    """Button setup creates OutageBoostButton only for generators."""
    coordinator = MagicMock()
    coordinator.data = {
        "gen1": _make_item(DEVICE_TYPE_GENERATOR, "Generator"),
        "tank1": _make_item(DEVICE_TYPE_PROPANE_MONITOR, "Propane Tank"),
    }
    entry = MagicMock()
    entry.entry_id = "entry1"
    hass.data[DOMAIN] = {"entry1": coordinator}

    added: list[OutageBoostButton] = []
    await button_platform.async_setup_entry(hass, entry, added.extend)
    assert len(added) == 1
    assert isinstance(added[0], OutageBoostButton)
    assert added[0].device_id == "gen1"

    coordinator.data = None
    added_empty: list[OutageBoostButton] = []
    await button_platform.async_setup_entry(hass, entry, added_empty.extend)
    assert added_empty == []


async def test_button_press_service_triggers_boost(hass: HomeAssistant) -> None:
    """Pressing the registered button entity via HA invokes async_trigger_boost."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="entry1",
        data={
            CONF_USERNAME: "user@example.com",
            CONF_REFRESH_TOKEN: "rt",
            CONF_DPOP_PEM: DPoPKey.generate().to_pem_str(),
        },
    )
    entry.add_to_hass(hass)

    data = {"12345": _make_item(DEVICE_TYPE_GENERATOR, "Generator")}
    with patch(
        "custom_components.generac.api.GeneracApiClient.async_get_data",
        return_value=data,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    with patch.object(
        GeneracDataUpdateCoordinator,
        "async_trigger_boost",
        new_callable=AsyncMock,
    ) as mock_boost:
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": "button.generator_outage_boost_poll"},
            blocking=True,
        )

    mock_boost.assert_awaited_once_with()
