"""Test the Generac diagnostics."""
from unittest.mock import MagicMock

from custom_components.generac.diagnostics import async_get_config_entry_diagnostics
from custom_components.generac.models import Item, Apparatus, ApparatusDetail


async def test_diagnostics(hass):
    """Test the diagnostics."""
    coordinator = MagicMock()
    coordinator.data = {
        "12345": Item(
            apparatus=Apparatus(
                serialNumber="1234567890",
                apparatusId=12345,
                localizedAddress="123 Main St",
            ),
            apparatusDetail=ApparatusDetail(
                deviceSsid="TestSSID",
            ),
        )
    }
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    hass.data = {"generac": {"test_entry_id": coordinator}}

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["data"]["12345"]["apparatus"]["serialNumber"] == "REDACTED"
    assert diagnostics["data"]["12345"]["apparatus"]["apparatusId"] == "REDACTED"
    assert diagnostics["data"]["12345"]["apparatus"]["localizedAddress"] == "REDACTED"
    assert diagnostics["data"]["12345"]["apparatusDetail"]["deviceSsid"] == "REDACTED"
