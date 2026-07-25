"""Tests for entry teardown in ``__init__.py``."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant

from custom_components.romande_energie import (
    SERVICE_UPDATE_NOW,
    async_unload_entry,
)
from custom_components.romande_energie.const import CONF_CONTRACT_ID, DOMAIN

from .conftest import build_config_entry


@pytest.fixture
def unload_ok(hass: HomeAssistant, monkeypatch) -> None:
    """Report every platform as unloading cleanly."""
    monkeypatch.setattr(
        hass.config_entries, "async_unload_platforms", AsyncMock(return_value=True)
    )


async def test_last_entry_removes_the_service(hass: HomeAssistant, unload_ok) -> None:
    entry = build_config_entry()
    entry.add_to_hass(hass)
    hass.data[DOMAIN] = {entry.entry_id: object()}
    hass.services.async_register(DOMAIN, SERVICE_UPDATE_NOW, AsyncMock())

    assert await async_unload_entry(hass, entry) is True

    assert DOMAIN not in hass.data
    assert not hass.services.has_service(DOMAIN, SERVICE_UPDATE_NOW)


async def test_other_entries_keep_their_coordinator_and_the_service(
    hass: HomeAssistant, unload_ok
) -> None:
    """Unloading one of two accounts must not disarm the other."""
    entry = build_config_entry()
    other = build_config_entry(data={CONF_CONTRACT_ID: "CONTRACT_OTHER"})
    entry.add_to_hass(hass)
    other.add_to_hass(hass)
    other_coordinator = object()
    hass.data[DOMAIN] = {entry.entry_id: object(), other.entry_id: other_coordinator}
    hass.services.async_register(DOMAIN, SERVICE_UPDATE_NOW, AsyncMock())

    assert await async_unload_entry(hass, entry) is True

    assert hass.data[DOMAIN] == {other.entry_id: other_coordinator}
    assert hass.services.has_service(DOMAIN, SERVICE_UPDATE_NOW)


async def test_missing_registry_is_reported_and_leaves_the_service_alone(
    hass: HomeAssistant, unload_ok, caplog
) -> None:
    """Setup stores the coordinator before the entry can load, so this is a bug.

    Unloading still has to succeed, but it must not take the service down with
    it — another entry may well still be using it.
    """
    entry = build_config_entry()
    entry.add_to_hass(hass)
    hass.services.async_register(DOMAIN, SERVICE_UPDATE_NOW, AsyncMock())

    assert await async_unload_entry(hass, entry) is True

    assert "No coordinator registry" in caplog.text
    assert hass.services.has_service(DOMAIN, SERVICE_UPDATE_NOW)


async def test_failed_platform_unload_keeps_everything(
    hass: HomeAssistant, monkeypatch, caplog
) -> None:
    entry = build_config_entry()
    entry.add_to_hass(hass)
    coordinator = object()
    hass.data[DOMAIN] = {entry.entry_id: coordinator}
    monkeypatch.setattr(
        hass.config_entries, "async_unload_platforms", AsyncMock(return_value=False)
    )

    assert await async_unload_entry(hass, entry) is False

    assert hass.data[DOMAIN] == {entry.entry_id: coordinator}
    assert "Failed to unload" in caplog.text
