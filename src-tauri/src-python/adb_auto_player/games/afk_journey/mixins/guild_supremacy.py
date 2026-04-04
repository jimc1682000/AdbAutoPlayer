"""AFK Journey Guild Supremacy Mixin."""

import logging
from time import sleep

from adb_auto_player.decorators import register_command
from adb_auto_player.exceptions import GameTimeoutError
from adb_auto_player.models.decorators import GUIMetadata
from adb_auto_player.util import SummaryGenerator

from ..base import AFKJourneyBase
from ..gui_category import AFKJCategory


class GuildSupremacyMixin(AFKJourneyBase):
    """Guild Supremacy Mixin."""

    SUMMONING_TEMPLATE = "guild_supremacy/summoning.png"
    GUILD_SUPREMACY_TEMPLATE = "guild_supremacy/guild_supremacy.png"
    REINFORCE_SEAL_TEMPLATE = "guild_supremacy/reinforce_the_seal_first.png"

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
        if not self._enter_guild_supremacy():
            return
        self._battle()
        logging.info("Guild Supremacy finished.")

    def _enter_guild_supremacy(self) -> bool:
        """Navigate to Guild Supremacy from Battle Modes.

        Returns:
            True if successfully entered, False if skipped.
        """
        logging.info("Entering Guild Supremacy...")
        self.navigate_to_battle_modes_screen()

        # Scroll down to find the guild supremacy section.
        if not self.game_find_template_match(self.GUILD_SUPREMACY_TEMPLATE):
            self.swipe_up(sy=1350, ey=500)
            sleep(3)

        # Check if still in summoning phase.
        if self.game_find_template_match(self.SUMMONING_TEMPLATE):
            logging.info("Still summoning Guild Boss, skipping.")
            return False

        result = self.game_find_template_match(self.GUILD_SUPREMACY_TEMPLATE)
        if result is None:
            logging.warning("Guild Supremacy not found on Battle Modes screen.")
            return False

        self.tap(result)
        sleep(3)

        # Check if seal is not yet reinforced.
        if self.game_find_template_match(self.REINFORCE_SEAL_TEMPLATE):
            logging.info("Seal not reinforced yet, skipping.")
            self.press_back_button()
            sleep(2)
            return False

        return True

    def _battle(self) -> None:
        """Execute the boss battle."""
        try:
            logging.debug("Start battle.")
            start = self.wait_for_template(
                template="battle/battle.png",
                timeout=self.MIN_TIMEOUT,
                timeout_message="Failed to find Battle button.",
            )
            sleep(2)
            self.tap(start)

            logging.debug("Skip battle.")
            skip = self.wait_for_template(
                template="battle/skip.png",
                timeout=self.MIN_TIMEOUT,
                timeout_message="Failed to find Skip button.",
            )
            self.tap(skip)
            sleep(4)

            # Dismiss result screen.
            if not self.handle_popup_messages():
                self.tap(self.CENTER_POINT)
                sleep(2)

            SummaryGenerator.increment("Guild Supremacy", "Battles")
        except GameTimeoutError as fail:
            logging.error(fail)
