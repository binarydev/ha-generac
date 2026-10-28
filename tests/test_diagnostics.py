"""Test the Generac diagnostics."""
from unittest.mock import MagicMock

from custom_components.generac.diagnostics import async_get_config_entry_diagnostics
from custom_components.generac.models import Apparatus
from custom_components.generac.models import ApparatusDetail
from custom_components.generac.models import Item


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

    assert diagnostics["data"]["device_0"]["apparatus"]["serialNumber"] == "REDACTED"
    assert diagnostics["data"]["device_0"]["apparatus"]["apparatusId"] == "REDACTED"
    assert (
        diagnostics["data"]["device_0"]["apparatus"]["localizedAddress"] == "REDACTED"
    )
    assert (
        diagnostics["data"]["device_0"]["apparatusDetail"]["deviceSsid"] == "REDACTED"
    )


async def test_diagnostics_redacts_identifiers_emails_and_ips(hass):
    """Device IDs never leak via dict keys; emails and IPs get correct labels."""
    coordinator = MagicMock()
    coordinator.data = {
        "98765": Item(
            apparatus=Apparatus(
                apparatusId=98765,
                panelId="PANEL-1",
                preferredDealerEmail="dealer@example.com",
                preferredDealerName="Dealer <dealer@example.com>",
                properties=[
                    Apparatus.Property(name="ip", value="192.0.2.10", type=1),
                    Apparatus.Property(name="ip6", value="2001:db8::1", type=2),
                ],
            ),
            apparatusDetail=ApparatusDetail(shortDeviceId="SHORT-1"),
        )
    }
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    hass.data = {"generac": {"test_entry_id": coordinator}}

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["status"] == "loaded"
    assert list(diagnostics["data"]) == ["device_0"]
    assert "98765" not in str(diagnostics)
    apparatus = diagnostics["data"]["device_0"]["apparatus"]
    assert apparatus["panelId"] == "REDACTED"
    assert apparatus["preferredDealerEmail"] == "REDACTED_EMAIL"
    assert apparatus["preferredDealerName"] == "REDACTED_EMAIL"
    assert apparatus["properties"][0]["value"] == "REDACTED_IPV4"
    assert apparatus["properties"][1]["value"] == "REDACTED_IPV6"
    assert diagnostics["data"]["device_0"]["apparatusDetail"]["shortDeviceId"] == (
        "REDACTED"
    )
    for secret in ("PANEL-1", "SHORT-1", "dealer@example.com", "192.0.2.10"):
        assert secret not in str(diagnostics)


async def test_diagnostics_before_entry_is_loaded(hass):
    """Diagnostics for an entry that never loaded don't raise KeyError."""
    entry = MagicMock()
    entry.entry_id = "missing"
    hass.data = {}
    assert await async_get_config_entry_diagnostics(hass, entry) == {
        "status": "not_loaded",
        "data": {},
    }
