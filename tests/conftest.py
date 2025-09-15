"""Global fixtures for generac integration."""
from unittest.mock import patch

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations defined in the test dir."""
    yield


@pytest.fixture
def bypass_get_data():
    """Bypass coordinator get data."""

    async def mock_first_refresh(self):
        self.last_update_success = True

    with patch(
        "custom_components.generac.coordinator.GeneracDataUpdateCoordinator.async_config_entry_first_refresh",
        mock_first_refresh,
    ):
        yield


@pytest.fixture
def error_on_get_data():
    """Simulate error when coordinator get data."""
    with patch(
        "custom_components.generac.api.GeneracApiClient.async_get_data",
        side_effect=Exception,
    ):
        yield
