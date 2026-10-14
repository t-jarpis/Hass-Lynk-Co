import asyncio
import logging
from datetime import datetime, timedelta

from custom_components.lynkco.remote_control_manager import force_update_data

from .const import (
    COORDINATOR,
    DOMAIN,
    EXPECTED_STATE_ENGINE_OFF,
    EXPECTED_STATE_ENGINE_ON,
    EXPECTED_STATE_UNLOCKED,
    EXPECTED_STATE_LOCKED,
    EXPECTED_STATE_CLIMATE_OFF,
    EXPECTED_STATE_CLIMATE_ON,
)


_LOGGER = logging.getLogger(__name__)


_MISSING = object()

_LOCKED_VALUES = ("DOOR_LOCKS_STATUS_LOCKED", "DOOR_LOCKS_STATUS_SAFE_LOCKED")


def _lookup(data, path):
    """Follow a dotted path in the coordinator data, like the entities do."""
    for key in path.split("."):
        if isinstance(data, dict) and key in data:
            data = data[key]
        else:
            return _MISSING
    return data


def _as_bool(value):
    """Interpret a value the same way the binary sensors do."""
    if value == "ENGINE_RUNNING":
        return True
    if value == "ENGINE_OFF":
        return False
    return bool(value)


def _is_locked(value):
    return value in _LOCKED_VALUES


def _is_unlocked(value):
    return value is not None and value != "NO_ENGINE_INFO" and not _is_locked(value)


class ExpectedStateMonitor:
    def __init__(self):
        self.expected_states = {}
        self.loop_running = False
        self.lock = asyncio.Lock()
        # state -> (path in coordinator.data, predicate on the value at that path).
        # The paths are the same ones the matching entities read from.
        self.state_map = {
            EXPECTED_STATE_ENGINE_ON: (
                "vehicle_shadow.bvs.engineStatus",
                lambda v: _as_bool(v) is True,
            ),
            EXPECTED_STATE_ENGINE_OFF: (
                "vehicle_shadow.bvs.engineStatus",
                lambda v: v == "ENGINE_OFF",
            ),
            EXPECTED_STATE_UNLOCKED: (
                "vehicle_shadow.vls.doorLocksStatus",
                _is_unlocked,
            ),
            EXPECTED_STATE_LOCKED: (
                "vehicle_shadow.vls.doorLocksStatus",
                _is_locked,
            ),
            EXPECTED_STATE_CLIMATE_ON: (
                "vehicle_record.climate.preClimateActive",
                lambda v: _as_bool(v) is True,
            ),
            EXPECTED_STATE_CLIMATE_OFF: (
                "vehicle_record.climate.preClimateActive",
                lambda v: _as_bool(v) is False,
            ),
        }

    async def expect_state(self, state, hass, entry):
        """Expect a specific state to be reached and manage the monitoring loop."""
        async with self.lock:
            self.expected_states[state] = datetime.now()
            await self.remove_opposite(state)
            if not self.loop_running:
                self.loop_running = True
                asyncio.create_task(self.monitor_states(hass, entry))

    async def remove_opposite(self, state):
        """Remove the opposite state if present."""
        opposite_states = {
            EXPECTED_STATE_ENGINE_ON: EXPECTED_STATE_ENGINE_OFF,
            EXPECTED_STATE_ENGINE_OFF: EXPECTED_STATE_ENGINE_ON,
            EXPECTED_STATE_UNLOCKED: EXPECTED_STATE_LOCKED,
            EXPECTED_STATE_LOCKED: EXPECTED_STATE_UNLOCKED,
            EXPECTED_STATE_CLIMATE_ON: EXPECTED_STATE_CLIMATE_OFF,
            EXPECTED_STATE_CLIMATE_OFF: EXPECTED_STATE_CLIMATE_ON,
        }

        opposite_state = opposite_states.get(state)
        if opposite_state in self.expected_states:
            _LOGGER.info(f"Removing {opposite_state} since we are expecting {state}")
            del self.expected_states[opposite_state]

    async def monitor_states(self, hass, entry):
        """Monitor expected states and update them continuously."""
        poll_time = 5
        try:
            while True:
                await asyncio.sleep(poll_time)
                await force_update_data(hass, entry)
                coordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR]

                async with self.lock:
                    current_states = coordinator.data
                    if self.check_and_update_states(current_states):
                        break
                poll_time = min(30, poll_time + 10)
        finally:
            self.loop_running = False

    def check_and_update_states(self, current_states):
        """Check and update states based on current data. Return True if monitoring should stop."""
        to_remove = []
        now = datetime.now()
        for state, timestamp in self.expected_states.items():
            path, is_expected = self.state_map[state]
            actual_value = _lookup(current_states or {}, path)
            if actual_value is not _MISSING and is_expected(actual_value):
                _LOGGER.info(f"State {state} reached the expected value.")
                to_remove.append(state)
            elif (now - timestamp) > timedelta(minutes=3):
                _LOGGER.warning(
                    f"State {state} was not confirmed by the vehicle within 3 minutes. "
                    "The command was accepted by Lynk & Co, but the car has not reported the new state yet."
                )
                to_remove.append(state)

        for state in to_remove:
            del self.expected_states[state]

        return (
            not self.expected_states
        )  # Return True if no states are left, stopping the monitor
