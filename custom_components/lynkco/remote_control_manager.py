import asyncio
import logging
import uuid

import aiohttp
from homeassistant.exceptions import HomeAssistantError

from .const import (
    COORDINATOR,
    DATA_IS_FORCE_UPDATE,
    DOMAIN,
)
from .http_client import REQUEST_TIMEOUT, get_session
from .token_manager import get_ccc_token, get_user_id

_LOGGER = logging.getLogger(__name__)



async def make_http_request(hass, url, data, vin):
    """Send a remote control command to the Lynk & Co backend.

    Returns True when the backend accepted the command (HTTP 200).
    Raises HomeAssistantError otherwise, so the failure is reported to the
    caller of the service (UI, automation, REST API) instead of being silently
    logged.
    """
    ccc_token = await get_ccc_token(hass)
    if not ccc_token:
        raise HomeAssistantError(
            "Could not get a valid Lynk & Co token. Try the refresh_tokens service or re-authenticate the integration."
        )
    user_id = await get_user_id(hass, ccc_token, vin)
    if not user_id:
        raise HomeAssistantError("Could not determine the Lynk & Co user id for this vehicle.")
    headers = {
        "user-agent": "LynkCo/3016 CFNetwork/1492.0.1 Darwin/23.3.0",
        "accept": "application/json",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "userId": user_id,
        "X-B3-TraceId": uuid.uuid4().hex,
        "Authorization": f"Bearer {ccc_token}",
    }
    try:
        session = get_session(hass)
        async with session.post(
            url, headers=headers, json=data, timeout=REQUEST_TIMEOUT
        ) as response:
            body = await response.text()
            if response.status == 200:
                _LOGGER.debug("Lynk backend accepted command: %s", body[:500])
                return True
            _LOGGER.error(
                f"Failed to execute command, HTTP status: {response.status}, response: {body}"
            )
            raise HomeAssistantError(
                f"Lynk & Co rejected the command (HTTP {response.status})"
            )
    except (aiohttp.ClientError, asyncio.TimeoutError) as err:
        reason = str(err) or type(err).__name__
        _LOGGER.error("Could not reach the Lynk backend: %s", reason)
        raise HomeAssistantError(
            f"Could not reach the Lynk & Co backend: {reason}"
        ) from err


async def start_climate(hass, vin, climate_level, duration_in_minutes):
    data = {
        "climateLevel": climate_level,
        "command": "START",
        "dayofweek": ["ONCE"],
        "durationInSeconds": duration_in_minutes * 60,
        "scheduledTime": 10,
        "heatItems": ["ALL"],
        "startTimeOfDay": "00:00",
        "timerId": "1",
        "ventilationItems": ["ALL"],
    }
    if await make_http_request(
        hass,
        f"https://remote-vehicle-control-tls.aion.connectedcar.cloud/api/v1/rvc/vehicles/{vin}/remotecontrol/climate",
        data,
        vin,
    ):
        _LOGGER.info("Successfully sent start climate to Lynk backend")


async def stop_climate(hass, vin):
    data = {
        "command": "STOP",
        "dayofweek": ["ONCE"],
        "startTimeOfDay": "00:00",
        "durationInSeconds": 1,
        "timerId": "1",
        "ventilationItems": ["ALL"],
        "scheduledTime": 10,
    }
    if await make_http_request(
        hass,
        f"https://remote-vehicle-control-tls.aion.connectedcar.cloud/api/v1/rvc/vehicles/{vin}/remotecontrol/climate",
        data,
        vin,
    ):
        _LOGGER.info("Successfully sent stop climate to Lynk backend")


async def start_engine(hass, vin, duration_in_minutes):
    data = {
        "command": "START",
        "durationInSeconds": duration_in_minutes * 60,
    }
    if await make_http_request(
        hass,
        f"https://remote-vehicle-control-tls.aion.connectedcar.cloud/api/v1/rvc/vehicles/{vin}/remotecontrol/engine",
        data,
        vin,
    ):
        _LOGGER.info("Successfully sent start engine to Lynk backend")


async def stop_engine(hass, vin):
    data = {
        "command": "STOP",
        "durationInSeconds": 1800,
    }
    if await make_http_request(
        hass,
        f"https://remote-vehicle-control-tls.aion.connectedcar.cloud/api/v1/rvc/vehicles/{vin}/remotecontrol/engine",
        data,
        vin,
    ):
        _LOGGER.info("Successfully sent stop engine to Lynk backend")


async def lock_doors(hass, vin):
    data = {
        "doorItems": ["ALL_DOORS"],
        "targetItems": [
            "TRUNK",
            "HOOD",
            "TANK_FLAG",
            "BACK_CHARGE_LID",
            "FRONT_CHARGE_LID",
        ],
    }
    if await make_http_request(
        hass,
        f"https://remote-vehicle-control-tls.aion.connectedcar.cloud/api/v1/rvc/vehicles/{vin}/remotecontrol/doorlock",
        data,
        vin,
    ):
        _LOGGER.info("Successfully sent lock doors to Lynk backend")


async def unlock_doors(hass, vin):
    data = {
        "doorItems": ["ALL_DOORS"],
        "targetItems": [
            "TRUNK",
            "FRONT_CHARGE_LID",
        ],
        "durationInSeconds": 15,
        "timeStart": 0,
    }
    if await make_http_request(
        hass,
        f"https://remote-vehicle-control-tls.aion.connectedcar.cloud/api/v1/rvc/vehicles/{vin}/remotecontrol/doorunlock",
        data,
        vin,
    ):
        _LOGGER.info("Successfully sent unlock doors to Lynk backend")


async def start_flash_lights(hass, vin):
    data = {
        "command": "START",
        "control": "FLASH",
    }
    if await make_http_request(
        hass,
        f"https://remote-vehicle-control-tls.aion.connectedcar.cloud/api/v1/rvc/vehicles/{vin}/remotecontrol/honkflash",
        data,
        vin,
    ):
        _LOGGER.info("Successfully sent start flash to Lynk backend")


async def start_honk(hass, vin):
    data = {
        "command": "START",
        "control": "HONK",
    }
    if await make_http_request(
        hass,
        f"https://remote-vehicle-control-tls.aion.connectedcar.cloud/api/v1/rvc/vehicles/{vin}/remotecontrol/honkflash",
        data,
        vin,
    ):
        _LOGGER.info("Successfully sent start honk to Lynk backend")


async def start_honk_flash(hass, vin):
    data = {
        "command": "START",
        "control": "HONK_FLASH",
    }
    if await make_http_request(
        hass,
        f"https://remote-vehicle-control-tls.aion.connectedcar.cloud/api/v1/rvc/vehicles/{vin}/remotecontrol/honkflash",
        data,
        vin,
    ):
        _LOGGER.info("Successfully sent start honk and flash to Lynk backend")


async def stop_flash_lights(hass, vin):
    data = {
        "command": "STOP",
        "control": "FLASH",
    }
    if await make_http_request(
        hass,
        f"https://remote-vehicle-control-tls.aion.connectedcar.cloud/api/v1/rvc/vehicles/{vin}/remotecontrol/honkflash",
        data,
        vin,
    ):
        _LOGGER.info("Successfully sent stop flash to Lynk backend")


async def stop_honk(hass, vin):
    data = {
        "command": "STOP",
        "control": "HONK",
    }
    if await make_http_request(
        hass,
        f"https://remote-vehicle-control-tls.aion.connectedcar.cloud/api/v1/rvc/vehicles/{vin}/remotecontrol/honkflash",
        data,
        vin,
    ):
        _LOGGER.info("Successfully sent stop honk to Lynk backend")


async def force_update_data(hass, entry):
    """Trigger a force data update, bypassing the nightly time check."""
    hass.data[DOMAIN][entry.entry_id][DATA_IS_FORCE_UPDATE] = True
    coordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR]
    await coordinator.async_request_refresh()
