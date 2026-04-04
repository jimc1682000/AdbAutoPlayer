"""AFK Journey Guild Supremacy Mixin."""

import logging
from time import sleep

from adb_auto_player.decorators import register_command
from adb_auto_player.exceptions import GameTimeoutError
from adb_auto_player.models.decorators import GUIMetadata
from adb_auto_player.models.geometry import Point
from adb_auto_player.util import SummaryGenerator

from ..base import AFKJourneyBase
from ..gui_category import AFKJCategory


class GuildSupremacyMixin(AFKJourneyBase):
    """Guild Supremacy Mixin."""

    @register_command(
        name="GuildSupremacy",
        gui=GUIMetadata(
            label="Guild Supremacy",
            category=AFKJCategory.GAME_MODES,
        ),
    )
    def run_guild_supremacy(self) -> None:
        """Run Guild Supremacy boss battle."""
        self.start_up(device_streaming=False)
        self._enter_guild_supremacy()
        self._battle()
        logging.info("Guild Supremacy finished.")

    def _enter_guild_supremacy(self) -> None:
        """Navigate to Guild Supremacy from Battle Modes."""
        logging.info("Entering Guild Supremacy...")
        self.navigate_to_battle_modes_screen()
        result = self._find_in_battle_modes(
            template="battle_modes/guild_supremacy.png",
            timeout_message="Guild Supremacy not found.",
        )
        self._tap_till_template_disappears(result.template)
        sleep(3)

    def _battle(self) -> None:
        """Execute the boss battle."""
        try:
            logging.debug("Start battle.")
            start = self.wait_for_template(
                template="guild_supremacy/battle.png",
                timeout=self.MIN_TIMEOUT,
                timeout_message="Failed to find Battle button.",
            )
            sleep(2)
            self.tap(start)

            logging.debug("Skip battle.")
            skip = self.wait_for_template(
                template="guild_supremacy/skip.png",
                timeout=self.MIN_TIMEOUT,
                timeout_message="Failed to find Skip button.",
            )
            self.tap(skip)

            logging.debug("Battle complete.")
            done = self.wait_for_template(
                template="guild_supremacy/done.png",
                timeout=self.MIN_TIMEOUT,
                timeout_message="Failed to confirm battle completion.",
            )
            sleep(4)
            self.tap(done)
            sleep(2)

            SummaryGenerator.increment("Guild Supremacy", "Battles")
        except GameTimeoutError as fail:
            logging.error(fail)
