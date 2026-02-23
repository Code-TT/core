"""Test IPv6 functionality for Cloudflare integration."""

from unittest.mock import MagicMock, patch

import pytest

from homeassistant.components.cloudflare.const import (
    CONF_IP_VERSION,
    CONF_RECORDS,
    DEFAULT_IP_VERSION,
    DOMAIN,
    IP_VERSION_AUTO,
    IP_VERSION_BOTH,
    IP_VERSION_IPV4,
    IP_VERSION_IPV6,
)
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_API_TOKEN, CONF_SOURCE, CONF_ZONE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util.location import LocationInfo

from . import (
    ENTRY_CONFIG,
    USER_INPUT,
    USER_INPUT_IP_VERSION,
    USER_INPUT_RECORDS,
    USER_INPUT_ZONE,
    init_integration,
    patch_async_setup_entry,
)

from tests.common import MockConfigEntry

LOCATION_PATCH_TARGET = (
    "homeassistant.components.cloudflare.coordinator.async_detect_location_info"
)

# Complete LocationInfo with all required fields
IPv4_LOCATION = LocationInfo(
    ip="192.0.2.100",
    country_code="US",
    currency="USD",
    region_code="CA",
    region_name="California",
    city="San Diego",
    zip_code="92122",
    time_zone="America/Los_Angeles",
    latitude=32.8594,
    longitude=-117.2073,
    use_metric=False,
)

IPv6_LOCATION = LocationInfo(
    ip="2001:db8::100",
    country_code="US",
    currency="USD",
    region_code="CA",
    region_name="California",
    city="San Diego",
    zip_code="92122",
    time_zone="America/Los_Angeles",
    latitude=32.8594,
    longitude=-117.2073,
    use_metric=False,
)


async def test_config_flow_ip_version_step(
    hass: HomeAssistant, cfupdate_flow: MagicMock
) -> None:
    """Test IP version step in config flow."""
    mock_client = cfupdate_flow.return_value

    # Mock both A and AAAA records (new API returns all types)
    mock_client.list_dns_records.return_value = [
        {"id": "record1", "name": "example.com", "type": "A", "content": "192.0.2.1"},
        {"id": "record2", "name": "example.com", "type": "AAAA", "content": "2001:db8::1"},
    ]

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={CONF_SOURCE: SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT_ZONE
    )

    # Should now be at IP version step
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "ip_version"

    # Test selecting IPv6 only
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_IP_VERSION: IP_VERSION_IPV6}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "records"

    # Complete the flow
    with patch_async_setup_entry():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT_RECORDS
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_IP_VERSION] == IP_VERSION_IPV6


async def test_config_flow_default_ip_version(
    hass: HomeAssistant, cfupdate_flow: MagicMock
) -> None:
    """Test default IP version is auto."""
    mock_client = cfupdate_flow.return_value

    # Mock both A and AAAA records
    mock_client.list_dns_records.return_value = [
        {"id": "record1", "name": "example.com", "type": "A", "content": "192.0.2.1"},
        {"id": "record2", "name": "example.com", "type": "AAAA", "content": "2001:db8::1"},
    ]

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={CONF_SOURCE: SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT_ZONE
    )

    # Check default value in schema
    assert result["type"] is FlowResultType.FORM
    data_schema = result["data_schema"].schema
    ip_version_field = next(
        field for field in data_schema.keys() if field == CONF_IP_VERSION
    )
    assert ip_version_field.default() == DEFAULT_IP_VERSION


async def test_coordinator_ipv4_only(
    hass: HomeAssistant, cfupdate: MagicMock
) -> None:
    """Test coordinator with IPv4 only mode."""
    mock_client = cfupdate.return_value
    mock_client.list_zones.return_value = [{"id": "zone1", "name": "mock.com"}]
    mock_client.list_dns_records.return_value = [
        {
            "id": "record1",
            "name": "ha.mock.com",
            "type": "A",
            "content": "192.0.2.1",
            "proxied": False,
        },
        {
            "id": "record2",
            "name": "ha.mock.com",
            "type": "AAAA",
            "content": "2001:db8::1",
            "proxied": False,
        },
    ]

    # Mock IPv4 detection only
    with patch(LOCATION_PATCH_TARGET, return_value=IPv4_LOCATION):
        entry = await init_integration(
            hass,
            data={
                CONF_API_TOKEN: "test-token",
                CONF_ZONE: "mock.com",
                CONF_RECORDS: ["ha.mock.com"],
                CONF_IP_VERSION: IP_VERSION_IPV4,
            },
        )

        # Get coordinator from runtime_data (proper pattern)
        coordinator = entry.runtime_data
        await coordinator.async_refresh()

    # Should only update A record
    mock_client.update_dns_record.assert_called_once()
    call_kwargs = mock_client.update_dns_record.call_args.kwargs
    assert call_kwargs["record_type"] == "A"
    assert call_kwargs["record_content"] == "192.0.2.100"


async def test_coordinator_ipv6_only(
    hass: HomeAssistant, cfupdate: MagicMock
) -> None:
    """Test coordinator with IPv6 only mode (DS-Lite scenario)."""
    mock_client = cfupdate.return_value
    mock_client.list_zones.return_value = [{"id": "zone1", "name": "mock.com"}]
    mock_client.list_dns_records.return_value = [
        {
            "id": "record1",
            "name": "ha.mock.com",
            "type": "A",
            "content": "192.0.2.1",
            "proxied": False,
        },
        {
            "id": "record2",
            "name": "ha.mock.com",
            "type": "AAAA",
            "content": "2001:db8::1",
            "proxied": False,
        },
    ]

    # Mock IPv6 detection only
    with patch(LOCATION_PATCH_TARGET, return_value=IPv6_LOCATION):
        entry = await init_integration(
            hass,
            data={
                CONF_API_TOKEN: "test-token",
                CONF_ZONE: "mock.com",
                CONF_RECORDS: ["ha.mock.com"],
                CONF_IP_VERSION: IP_VERSION_IPV6,
            },
        )

        coordinator = entry.runtime_data
        await coordinator.async_refresh()

    # Should only update AAAA record
    mock_client.update_dns_record.assert_called_once()
    call_kwargs = mock_client.update_dns_record.call_args.kwargs
    assert call_kwargs["record_type"] == "AAAA"
    assert call_kwargs["record_content"] == "2001:db8::100"


async def test_coordinator_auto_mode_both_available(
    hass: HomeAssistant, cfupdate: MagicMock
) -> None:
    """Test auto mode with both IPv4 and IPv6 available."""
    mock_client = cfupdate.return_value
    mock_client.list_zones.return_value = [{"id": "zone1", "name": "mock.com"}]
    mock_client.list_dns_records.return_value = [
        {
            "id": "record1",
            "name": "ha.mock.com",
            "type": "A",
            "content": "192.0.2.1",
            "proxied": False,
        },
        {
            "id": "record2",
            "name": "ha.mock.com",
            "type": "AAAA",
            "content": "2001:db8::1",
            "proxied": False,
        },
    ]

    # Mock both IPv4 and IPv6 detection
    with patch(
        LOCATION_PATCH_TARGET,
        side_effect=[IPv4_LOCATION, IPv6_LOCATION],
    ):
        entry = await init_integration(
            hass,
            data={
                CONF_API_TOKEN: "test-token",
                CONF_ZONE: "mock.com",
                CONF_RECORDS: ["ha.mock.com"],
                CONF_IP_VERSION: IP_VERSION_AUTO,
            },
        )

        coordinator = entry.runtime_data
        await coordinator.async_refresh()

    # Should update both records
    assert mock_client.update_dns_record.call_count == 2


async def test_coordinator_both_ip_versions(
    hass: HomeAssistant, cfupdate: MagicMock
) -> None:
    """Test coordinator with both IPv4 and IPv6 mode."""
    mock_client = cfupdate.return_value
    mock_client.list_zones.return_value = [{"id": "zone1", "name": "mock.com"}]
    mock_client.list_dns_records.return_value = [
        {
            "id": "record1",
            "name": "ha.mock.com",
            "type": "A",
            "content": "192.0.2.1",
            "proxied": False,
        },
        {
            "id": "record2",
            "name": "ha.mock.com",
            "type": "AAAA",
            "content": "2001:db8::1",
            "proxied": False,
        },
    ]

    # Mock both IPv4 and IPv6 detection
    with patch(
        LOCATION_PATCH_TARGET,
        side_effect=[IPv4_LOCATION, IPv6_LOCATION],
    ):
        entry = await init_integration(
            hass,
            data={
                CONF_API_TOKEN: "test-token",
                CONF_ZONE: "mock.com",
                CONF_RECORDS: ["ha.mock.com"],
                CONF_IP_VERSION: IP_VERSION_BOTH,
            },
        )

        coordinator = entry.runtime_data
        await coordinator.async_refresh()

    # Should update both records
    assert mock_client.update_dns_record.call_count == 2

    # Check A record update
    a_call = mock_client.update_dns_record.call_args_list[0]
    assert a_call.kwargs["record_type"] == "A"
    assert a_call.kwargs["record_content"] == "192.0.2.100"

    # Check AAAA record update
    aaaa_call = mock_client.update_dns_record.call_args_list[1]
    assert aaaa_call.kwargs["record_type"] == "AAAA"
    assert aaaa_call.kwargs["record_content"] == "2001:db8::100"


async def test_coordinator_no_ip_detected(
    hass: HomeAssistant, cfupdate: MagicMock
) -> None:
    """Test coordinator when no IP address can be detected."""
    mock_client = cfupdate.return_value
    mock_client.list_zones.return_value = [{"id": "zone1", "name": "mock.com"}]
    mock_client.list_dns_records.return_value = [
        {
            "id": "record1",
            "name": "ha.mock.com",
            "type": "A",
            "content": "192.0.2.1",
            "proxied": False,
        },
    ]

    # Mock no IP detection
    with patch(LOCATION_PATCH_TARGET, return_value=None):
        entry = await init_integration(
            hass,
            data={
                CONF_API_TOKEN: "test-token",
                CONF_ZONE: "mock.com",
                CONF_RECORDS: ["ha.mock.com"],
                CONF_IP_VERSION: IP_VERSION_AUTO,
            },
        )

        coordinator = entry.runtime_data

        # Trigger update - should raise UpdateFailed
        with pytest.raises(UpdateFailed, match="Could not detect any external IP address"):
            await coordinator.async_refresh()


async def test_coordinator_ipv4_only_mode_skips_aaaa(
    hass: HomeAssistant, cfupdate: MagicMock
) -> None:
    """Test that IPv4 only mode doesn't update AAAA records even if IPv6 is detected."""
    mock_client = cfupdate.return_value
    mock_client.list_zones.return_value = [{"id": "zone1", "name": "mock.com"}]
    mock_client.list_dns_records.return_value = [
        {
            "id": "record1",
            "name": "ha.mock.com",
            "type": "A",
            "content": "192.0.2.1",
            "proxied": False,
        },
        {
            "id": "record2",
            "name": "ha.mock.com",
            "type": "AAAA",
            "content": "2001:db8::1",
            "proxied": False,
        },
    ]

    # Even though both IPs are detected, IPv4 mode only uses IPv4
    with patch(
        LOCATION_PATCH_TARGET,
        side_effect=[IPv4_LOCATION, IPv6_LOCATION],
    ):
        entry = await init_integration(
            hass,
            data={
                CONF_API_TOKEN: "test-token",
                CONF_ZONE: "mock.com",
                CONF_RECORDS: ["ha.mock.com"],
                CONF_IP_VERSION: IP_VERSION_IPV4,
            },
        )

        coordinator = entry.runtime_data
        await coordinator.async_refresh()

    # Should only update A record (not AAAA)
    mock_client.update_dns_record.assert_called_once()
    call_kwargs = mock_client.update_dns_record.call_args.kwargs
    assert call_kwargs["record_type"] == "A"


async def test_coordinator_ipv6_only_mode_skips_a(
    hass: HomeAssistant, cfupdate: MagicMock
) -> None:
    """Test that IPv6 only mode doesn't update A records even if IPv4 is detected."""
    mock_client = cfupdate.return_value
    mock_client.list_zones.return_value = [{"id": "zone1", "name": "mock.com"}]
    mock_client.list_dns_records.return_value = [
        {
            "id": "record1",
            "name": "ha.mock.com",
            "type": "A",
            "content": "192.0.2.1",
            "proxied": False,
        },
        {
            "id": "record2",
            "name": "ha.mock.com",
            "type": "AAAA",
            "content": "2001:db8::1",
            "proxied": False,
        },
    ]

    # Even though both IPs are detected, IPv6 mode only uses IPv6
    with patch(
        LOCATION_PATCH_TARGET,
        side_effect=[IPv4_LOCATION, IPv6_LOCATION],
    ):
        entry = await init_integration(
            hass,
            data={
                CONF_API_TOKEN: "test-token",
                CONF_ZONE: "mock.com",
                CONF_RECORDS: ["ha.mock.com"],
                CONF_IP_VERSION: IP_VERSION_IPV6,
            },
        )

        coordinator = entry.runtime_data
        await coordinator.async_refresh()

    # Should only update AAAA record (not A)
    mock_client.update_dns_record.assert_called_once()
    call_kwargs = mock_client.update_dns_record.call_args.kwargs
    assert call_kwargs["record_type"] == "AAAA"