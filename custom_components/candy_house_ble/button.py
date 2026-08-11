"""Button entities for CANDY HOUSE BLE."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CandyHouseConfigEntry
from .const import CONF_MODEL, MODEL_BOT_2
from .entity import CandyHouseEntity
from .protocol import BOT_2_SCRIPT_COUNT


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CandyHouseConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the ten fixed Bot 2 script buttons."""
    if entry.data[CONF_MODEL] == MODEL_BOT_2:
        async_add_entities(
            [
                SesameBot2RunScriptButton(entry, script_index)
                for script_index in range(BOT_2_SCRIPT_COUNT)
            ]
        )


class SesameBot2RunScriptButton(CandyHouseEntity, ButtonEntity):
    """Run one numbered Bot 2 script stored on the physical device."""

    _attr_translation_key = "run_script"

    def __init__(
        self, entry: CandyHouseConfigEntry, script_index: int
    ) -> None:
        super().__init__(entry, f"run_script_{script_index}")
        self.script_index = script_index
        self._attr_translation_placeholders = {"index": str(script_index)}

    @property
    def available(self) -> bool:
        """Require one authenticated status before allowing physical action."""
        return self.coordinator.data is not None

    async def async_press(self) -> None:
        """Run this numbered script exactly once."""
        await self.coordinator.async_run_script(self.script_index)
