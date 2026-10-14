"""Shared HTTP helpers for the Lynk & Co backend calls."""

import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)


def get_session(hass) -> aiohttp.ClientSession:
    """Return Home Assistant's shared session (connection reuse).

    Certificate verification stays disabled, exactly as before.
    """
    return async_get_clientsession(hass, verify_ssl=False)
