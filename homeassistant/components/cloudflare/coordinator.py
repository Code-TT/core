"""Contains the Coordinator for updating the IP addresses of your Cloudflare DNS records."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from logging import getLogger
import socket

import pycfdns

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_TOKEN, CONF_ZONE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util.location import async_detect_location_info
from homeassistant.util.network import is_ipv4_address, is_ipv6_address

from .const import (
    CONF_IP_VERSION,
    CONF_RECORDS,
    DEFAULT_IP_VERSION,
    DEFAULT_UPDATE_INTERVAL,
    IP_VERSION_AUTO,
    IP_VERSION_BOTH,
    IP_VERSION_IPV4,
    IP_VERSION_IPV6,
)

_LOGGER = getLogger(__name__)

type CloudflareConfigEntry = ConfigEntry[CloudflareCoordinator]


class CloudflareCoordinator(DataUpdateCoordinator[None]):
    """Coordinates records updates."""

    config_entry: CloudflareConfigEntry
    client: pycfdns.Client
    zone: pycfdns.ZoneModel

    def __init__(
        self, hass: HomeAssistant, config_entry: CloudflareConfigEntry
    ) -> None:
        """Initialize an coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=config_entry.title,
            update_interval=timedelta(minutes=DEFAULT_UPDATE_INTERVAL),
        )

    async def _async_setup(self) -> None:
        """Set up the coordinator."""
        self.client = pycfdns.Client(
            api_token=self.config_entry.data[CONF_API_TOKEN],
            client_session=async_get_clientsession(self.hass),
        )

        try:
            self.zone = next(
                zone
                for zone in await self.client.list_zones()
                if zone["name"] == self.config_entry.data[CONF_ZONE]
            )
        except pycfdns.AuthenticationException as e:
            raise ConfigEntryAuthFailed from e
        except pycfdns.ComunicationException as e:
            raise UpdateFailed("Error communicating with API") from e

    async def _async_update_data(self) -> None:
        """Update records."""
        _LOGGER.debug("Starting update for zone %s", self.zone["name"])
        try:
            # Get all DNS records (both A and AAAA)
            records = await self.client.list_dns_records(zone_id=self.zone["id"])
            _LOGGER.debug("Records: %s", records)

            target_records: list[str] = self.config_entry.data[CONF_RECORDS]
            ip_version = self.config_entry.data.get(CONF_IP_VERSION, DEFAULT_IP_VERSION)

            # Detect IP addresses based on configuration
            external_ipv4 = None
            external_ipv6 = None

            # Determine which IP versions to detect
            detect_ipv4 = ip_version in (
                IP_VERSION_AUTO,
                IP_VERSION_IPV4,
                IP_VERSION_BOTH,
            )
            detect_ipv6 = ip_version in (
                IP_VERSION_AUTO,
                IP_VERSION_IPV6,
                IP_VERSION_BOTH,
            )

            # Auto mode: try IPv6 first (for DS-Lite), then IPv4
            if ip_version == IP_VERSION_AUTO:
                detect_ipv6 = True
                detect_ipv4 = True

            # Detect IPv4 address if needed
            if detect_ipv4:
                try:
                    location_info_v4 = await async_detect_location_info(
                        async_get_clientsession(self.hass, family=socket.AF_INET)
                    )
                    if location_info_v4 and is_ipv4_address(location_info_v4.ip):
                        external_ipv4 = location_info_v4.ip
                        _LOGGER.debug("Detected IPv4 address: %s", external_ipv4)
                except Exception as err:
                    _LOGGER.debug("IPv4 detection failed: %s", err)

            # Detect IPv6 address if needed
            if detect_ipv6:
                try:
                    location_info_v6 = await async_detect_location_info(
                        async_get_clientsession(self.hass, family=socket.AF_INET6)
                    )
                    if location_info_v6 and is_ipv6_address(location_info_v6.ip):
                        external_ipv6 = location_info_v6.ip
                        _LOGGER.debug("Detected IPv6 address: %s", external_ipv6)
                except Exception as err:
                    _LOGGER.debug("IPv6 detection failed: %s", err)

            # Check if we have at least one IP address
            if not external_ipv4 and not external_ipv6:
                raise UpdateFailed("Could not detect any external IP address")

            # Filter records that need updating
            updates = []
            for record in records:
                if record["name"] not in target_records:
                    continue

                new_ip = None
                if record["type"] == "A" and external_ipv4:
                    new_ip = external_ipv4
                elif record["type"] == "AAAA" and external_ipv6:
                    new_ip = external_ipv6
                else:
                    continue

                if record["content"] != new_ip:
                    updates.append((record, new_ip))
                    _LOGGER.debug(
                        "Record %s (%s) needs update: %s -> %s",
                        record["name"],
                        record["type"],
                        record["content"],
                        new_ip,
                    )

            if len(updates) == 0:
                _LOGGER.debug("All target records are up to date")
                return

            # Update all records that need changes
            await asyncio.gather(
                *[
                    self.client.update_dns_record(
                        zone_id=self.zone["id"],
                        record_id=record["id"],
                        record_content=new_ip,
                        record_name=record["name"],
                        record_type=record["type"],
                        record_proxied=record["proxied"],
                    )
                    for record, new_ip in updates
                ]
            )

            _LOGGER.debug(
                "Update for zone %s complete. Updated %s record(s)",
                self.zone["name"],
                len(updates),
            )

        except (
            pycfdns.AuthenticationException,
            pycfdns.ComunicationException,
        ) as e:
            raise UpdateFailed(
                f"Error updating zone {self.config_entry.data[CONF_ZONE]}"
            ) from e
