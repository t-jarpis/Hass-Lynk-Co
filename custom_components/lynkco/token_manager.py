import asyncio
import base64
import json
import logging
import os
import time
import uuid

import aiohttp
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store

from .http_client import REQUEST_TIMEOUT, get_session
from .const import (
    DOMAIN,
    STORAGE_CCC_TOKEN_KEY,
    STORAGE_REFRESH_TOKEN_KEY,
    STORAGE_TOKEN_KEY,
    STORAGE_USER_ID_KEY,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)
ccc_token_lock = asyncio.Lock()

DIR_PATH = os.path.dirname(os.path.realpath(__file__))


def decode_jwt_token(token):
    """Decode JWT token without signature verification."""
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    decoded_bytes = base64.urlsafe_b64decode(payload)
    decoded = decoded_bytes.decode("utf-8")
    return json.loads(decoded)


async def is_token_expired(token):
    """Check if the JWT token is expired."""
    decoded_token = decode_jwt_token(token)
    current_time = time.time()
    return decoded_token["exp"] < current_time


async def get_ccc_token(hass):
    """Retrieve the CCC token from file if is valid."""
    async with ccc_token_lock:
        token_storage = get_token_storage(hass)
        tokens = await token_storage.async_load() or {}
        ccc_token = tokens.get(STORAGE_CCC_TOKEN_KEY)
        if ccc_token is None or await is_token_expired(ccc_token):
            ccc_token = await refresh_tokens(hass)
    return ccc_token


def get_token_storage(hass):
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    if STORAGE_TOKEN_KEY not in hass.data[DOMAIN]:
        hass.data[DOMAIN][STORAGE_TOKEN_KEY] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}_tokens"
        )

    return hass.data[DOMAIN][STORAGE_TOKEN_KEY]


async def refresh_tokens(hass):
    token_storage = get_token_storage(hass)
    tokens = await token_storage.async_load() or {}
    refresh_token = tokens.get(STORAGE_REFRESH_TOKEN_KEY)
    if refresh_token is None:
        _LOGGER.error("Refresh token is None, re-authenticate")
        raise ConfigEntryAuthFailed("Token has expired, please re-authenticate.")
    headers = {
        "user-agent": "LynkCo/3016 CFNetwork/1492.0.1 Darwin/23.3.0",
        "accept": "application/json",
        "content-type": "application/x-www-form-urlencoded",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }
    data = {
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    try:
        async with get_session(hass).post(
            "https://login.lynkco.com/dc6c7c0c-5ba7-414a-a7d1-d62ca1f73d13/b2c_1a_signin_mfa/oauth2/v2.0/token",
            headers=headers,
            data=data,
            timeout=REQUEST_TIMEOUT,
        ) as response:
            status = response.status
            body = await response.json() if status == 200 else await response.text()
    except (aiohttp.ClientError, asyncio.TimeoutError) as err:
        # Temporary network problem: keep the stored tokens and let the caller retry.
        _LOGGER.error("Could not reach the Lynk & Co login service: %s", err or type(err).__name__)
        return None

    if status in (400, 401):
        # The refresh token is no longer accepted: only a new login helps.
        _LOGGER.error("Refresh token rejected (HTTP %s), re-authenticate", status)
        raise ConfigEntryAuthFailed("Token has expired, please re-authenticate.")
    if status != 200:
        _LOGGER.error("Failed to get new refresh token, HTTP status: %s", status)
        return None

    stored_tokens = await token_storage.async_load() or {}
    new_refresh_token = body.get("refresh_token")
    if not new_refresh_token:
        _LOGGER.error("New refresh token is None")
        raise ConfigEntryAuthFailed("Token has expired, please re-authenticate.")
    stored_tokens[STORAGE_REFRESH_TOKEN_KEY] = new_refresh_token
    _LOGGER.debug("Refreshed refresh token")

    access_token = body.get("access_token")
    if not access_token:
        _LOGGER.error("Access token is None")
        await token_storage.async_save(stored_tokens)
        return None

    ccc_token = await send_device_login(access_token, hass)
    if not ccc_token:
        _LOGGER.error("New ccc token is None, please re-authenticate")
        raise ConfigEntryAuthFailed("Token has expired, please re-authenticate.")
    _LOGGER.debug("Refreshed ccc token")
    stored_tokens[STORAGE_CCC_TOKEN_KEY] = ccc_token
    await token_storage.async_save(stored_tokens)
    return ccc_token


async def send_device_login(access_token: str, hass=None):
    headers = {
        "user-agent": "LynkCo/3016 CFNetwork/1492.0.1 Darwin/23.3.0",
        "accept": "application/json",
        "content-type": "application/json",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "X-Auth-Token": access_token,
        "api-version": "1",
    }
    data = {"deviceUuid": str(uuid.uuid4()), "isLogin": True}
    own_session = hass is None  # config flow has no hass-bound session yet
    session = (
        aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False))
        if own_session
        else get_session(hass)
    )
    try:
        async with session.post(
            "https://iam-service-prod.westeurope.cloudapp.azure.com/validate-session",
            headers=headers,
            json=data,
            timeout=REQUEST_TIMEOUT,
        ) as response:
            if response.status == 200:
                data = await response.json()
                return data["cccToken"]
            _LOGGER.error(
                f"Failed to send device login, status: {response.status}, response: {await response.text()}"
            )
    except (aiohttp.ClientError, asyncio.TimeoutError) as err:
        _LOGGER.error("Could not reach the Lynk & Co device login: %s", err or type(err).__name__)
    finally:
        if own_session:
            await session.close()
    return None


async def get_user_id(hass, ccc_token, vin):
    token_storage = get_token_storage(hass)
    tokens = await token_storage.async_load() or {}
    user_id = tokens.get(STORAGE_USER_ID_KEY)
    if user_id is not None:
        return user_id
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "Authorization": f"Bearer {ccc_token}",
    }
    try:
        async with get_session(hass).get(
            f"https://delegated-driver-tls.aion.connectedcar.cloud/delegated-driver/api/delegateddriver/v1/vehicle/{vin}/drivers",
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        ) as response:
            if response.status == 200:
                response_json = await response.json()
                drivers = response_json.get("drivers")
                if drivers:
                    user_id = drivers[0]["userId"]
                    tokens = await token_storage.async_load() or {}
                    tokens[STORAGE_USER_ID_KEY] = user_id
                    await token_storage.async_save(tokens)
                    return user_id
                _LOGGER.error("No drivers found in response")
            else:
                _LOGGER.error(
                    f"Failed to get user id, status: {response.status}, response: {await response.text()}"
                )
    except (aiohttp.ClientError, asyncio.TimeoutError) as err:
        _LOGGER.error("Could not reach the Lynk & Co driver service: %s", err or type(err).__name__)
    return None
