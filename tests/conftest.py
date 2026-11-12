"""Shared fixtures."""

import pytest

# pycares (used by aiohttp DNS) starts a daemon shutdown thread the first time a
# resolver is torn down. Start it before any test so the HA test harness does
# not flag it as a thread left behind by the first test.
try:
    import gc

    import pycares

    pycares.Channel()
    gc.collect()
except Exception:  # noqa: BLE001
    pass


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load custom_components/nature_remo."""
    yield
