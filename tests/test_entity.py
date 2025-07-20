"""Test the Generac entity."""
from unittest.mock import MagicMock

from custom_components.generac.entity import GeneracEntity
from custom_components.generac.models import Item, Apparatus, ApparatusDetail


def get_mock_item() -> Item:
    """Return a mock Item object."""
    return Item(
        apparatus=Apparatus(
            name="Test Generator",
            modelNumber="G12345",
        ),
        apparatusDetail=ApparatusDetail(),
    )


async def test_entity(hass):
    """Test the entity."""
    coordinator = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    item = get_mock_item()
    entity = GeneracEntity(coordinator, entry, "12345", item)
    entity.hass = hass
    entity.async_write_ha_state = MagicMock()

    assert entity.device_info == {
        "identifiers": {("generac", "12345")},
        "name": "Test Generator",
        "model": "G12345",
        "manufacturer": "Generac",
    }
    assert entity.device_state_attributes == {
        "attribution": "Data provided by https://app.mobilelinkgen.com/api. This is reversed engineered. Heavily inspired by https://github.com/digitaldan/openhab-addons/blob/generac-2.0/bundles/org.openhab.binding.generacmobilelink/README.md",
        "id": "12345",
        "integration": "generac",
    }
    assert entity.available is True

    # Test coordinator update
    new_item = Item(
        apparatus=Apparatus(
            name="New Test Generator",
            modelNumber="G67890",
        ),
        apparatusDetail=ApparatusDetail(),
    )
    coordinator.data = {"12345": new_item}
    entity._handle_coordinator_update()
    assert entity.item == new_item
    assert entity.async_write_ha_state.called