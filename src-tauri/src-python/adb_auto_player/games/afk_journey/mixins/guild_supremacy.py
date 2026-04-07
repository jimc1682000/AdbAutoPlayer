"""AFK Journey Guild Supremacy Mixin."""

import logging
import re
from time import sleep

import cv2
from adb_auto_player.decorators import register_command, register_custom_routine_choice
from adb_auto_player.exceptions import GameTimeoutError
from adb_auto_player.image_manipulation import Color, ColorFormat
from adb_auto_player.models.decorators import GUIMetadata
from adb_auto_player.models.geometry import Point
from adb_auto_player.models.image_manipulation import CropRegions
from adb_auto_player.ocr import PSM, TesseractBackend, TesseractConfig
from adb_auto_player.util import SummaryGenerator

from ..base import AFKJourneyBase
from ..gui_category import AFKJCategory


class GuildSupremacyMixin(AFKJourneyBase):
    """Guild Supremacy Mixin."""

    SUMMONING_TEMPLATE = "guild_supremacy/summoning.png"
    GUILD_SUPREMACY_TEMPLATE = "battle_modes/guild_supremacy.png"
    REINFORCE_SEAL_TEMPLATE = "guild_supremacy/reinforce_the_seal_first.png"
    CLAIM_TEMPLATE = "guild_supremacy/claim.png"
    RANKINGS_TEMPLATE = "guild_supremacy/rankings.png"
    RANKINGS_GIFT_TEMPLATE = "guild_supremacy/rankings_gift.png"
    HAND_TEMPLATE = "navigation/guild/hand.png"
    YESTERDAY_CONTRIBUTION_TEMPLATE = "guild_supremacy/yesterday_contribution.png"
    BATTLE_ENDED_TEMPLATE = "guild_supremacy/battle_ended.png"
    BATTLE_COUNT_SLICE_HEIGHT = 30

    @register_command(
        name="GuildSupremacy",
        gui=GUIMetadata(
            label="Guild Supremacy",
            category=AFKJCategory.GAME_MODES,
        ),
    )
    @register_custom_routine_choice(label="Guild Supremacy")
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

        if not self._navigate_to_guild_supremacy_boss():
            return False

        # Wait for either the contribution popup or the boss screen.
        try:
            result = self.wait_for_any_template(
                templates=[
                    self.YESTERDAY_CONTRIBUTION_TEMPLATE,
                    "battle/battle.png",
                    self.REINFORCE_SEAL_TEMPLATE,
                    self.HAND_TEMPLATE,
                ],
                timeout=10,
            )
            if result.template == self.YESTERDAY_CONTRIBUTION_TEMPLATE:
                logging.debug("Dismissing Yesterday's Contribution popup.")
                self.tap(Point(540, 1620))
                sleep(2)
        except GameTimeoutError:
            pass

        # May have landed on guild map instead of boss screen.
        self._tap_hand_if_stuck()

        if not self._is_seal_reinforced():
            return False

        self._claim_progress_rewards()
        self._claim_rankings_rewards()

        return True

    def _navigate_to_guild_supremacy_boss(self) -> bool:
        """Navigate from current state to Guild Supremacy boss screen.

        Returns:
            True if successfully navigated, False if skipped.
        """
        self.navigate_to_battle_modes_screen()

        try:
            result = self._find_in_battle_modes(
                template=self.GUILD_SUPREMACY_TEMPLATE,
                timeout_message="Guild Supremacy not found on Battle Modes screen.",
            )
        except GameTimeoutError:
            logging.warning("Guild Supremacy not found on Battle Modes screen.")
            return False

        # Check if still in summoning phase.
        if self.game_find_template_match(self.SUMMONING_TEMPLATE):
            logging.info("Still summoning Guild Boss, skipping.")
            return False

        self._tap_till_template_disappears(result.template)
        sleep(3)
        return True

    def _tap_hand_if_stuck(self) -> None:
        """Tap the hand icon if stuck on guild map instead of boss screen."""
        hand = self.game_find_template_match(self.HAND_TEMPLATE)
        if hand:
            logging.debug("Stuck on guild map, tapping hand icon...")
            self.tap(hand)
            sleep(3)

    def _is_seal_reinforced(self) -> bool:
        """Check if the seal has been reinforced.

        Returns:
            True if reinforced (can battle), False if not yet reinforced.
        """
        if self.game_find_template_match(self.REINFORCE_SEAL_TEMPLATE):
            logging.info("Seal not reinforced yet, skipping.")
            self.press_back_button()
            sleep(2)
            return False
        return True

    def _claim_progress_rewards(self) -> None:
        """Claim progress milestone rewards if available."""
        claim = self.game_find_template_match(self.CLAIM_TEMPLATE)
        if claim is None:
            return

        logging.info("Claiming progress rewards...")
        self.tap(claim)
        sleep(2)
        self._dismiss_popup()

    def _claim_rankings_rewards(self) -> None:
        """Tap Rankings button to claim rewards if gift icon is present."""
        gift = self.game_find_template_match(
            self.RANKINGS_GIFT_TEMPLATE,
            crop_regions=CropRegions(left=0.8, bottom=0.8),
        )
        if gift is None:
            return

        rankings = self.game_find_template_match(self.RANKINGS_TEMPLATE)
        if rankings is None:
            return

        logging.info("Claiming rankings rewards...")
        self.tap(rankings)
        sleep(2)
        self._dismiss_popup()

        # Return from rankings screen to boss screen.
        self.press_back_button()
        sleep(2)

    def _dismiss_popup(self) -> None:
        """Dismiss a popup via tap_to_close or tapping center."""
        if not self.handle_popup_messages():
            tap_to_close = self.game_find_template_match("tap_to_close.png")
            if tap_to_close:
                self.tap(tap_to_close)
                sleep(2)

    def _has_battle_remaining(self) -> bool:
        """Check if there are battles remaining via OCR on the Battle button count.

        Returns:
            True if battles remain, False if 0 remaining.
        """
        screenshot = self.get_screenshot()
        battle_btn = self.game_find_template_match("battle/battle.png")
        if battle_btn is None:
            return False

        x = battle_btn.box.top_left.x
        y = battle_btn.box.top_left.y + battle_btn.box.height
        w = battle_btn.box.width
        h = self.BATTLE_COUNT_SLICE_HEIGHT

        crop = screenshot[y : y + h, x : x + w]
        if crop.size == 0:
            return True

        gray = Color.to_grayscale(crop, ColorFormat.BGR)
        _, thresholded = cv2.threshold(
            gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU
        )

        ocr = TesseractBackend(config=TesseractConfig(psm=PSM.SINGLE_LINE))
        text = ocr.extract_text(thresholded)
        match = re.match(r"(\d+)/(\d+)", text.strip())
        if match:
            remaining = int(match.group(1))
            logging.info("Battle count: %s", text.strip())
            return remaining > 0

        return True

    def _battle(self) -> None:
        """Execute the boss battle."""
        try:
            logging.debug("Entering battle.")
            start = self.wait_for_template(
                template="battle/battle.png",
                timeout=self.MIN_TIMEOUT,
                timeout_message="Failed to find Battle button.",
            )

            if not self._has_battle_remaining():
                logging.info("No battles remaining (0/1), skipping.")
                return

            self.tap(start)
            sleep(2)

            logging.debug("Skipping battle.")
            skip = self.wait_for_template(
                template="guild_supremacy/skip.png",
                timeout=self.MIN_TIMEOUT,
                timeout_message="Failed to find Skip button.",
            )
            self.tap(skip)

            # Wait for "BATTLE ENDED" screen then dismiss it.
            self.wait_for_template(
                template=self.BATTLE_ENDED_TEMPLATE,
                timeout=15,
                timeout_message="BATTLE ENDED screen not found.",
            )
            self.tap(Point(540, 1620))
            sleep(2)

            SummaryGenerator.increment("Guild Supremacy", "Battles")
        except GameTimeoutError as fail:
            logging.error(fail)
