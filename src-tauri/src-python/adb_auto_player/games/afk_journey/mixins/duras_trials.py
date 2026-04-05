"""AFK Journey Dura's Trials Mixin."""

import logging
import re
from time import sleep

import cv2
import numpy as np
from adb_auto_player.decorators import register_command, register_custom_routine_choice
from adb_auto_player.exceptions import (
    AutoPlayerError,
    AutoPlayerWarningError,
)
from adb_auto_player.image_manipulation import Color, ColorFormat
from adb_auto_player.models.decorators import GUIMetadata
from adb_auto_player.models.image_manipulation import CropRegions
from adb_auto_player.models.template_matching import TemplateMatchResult
from adb_auto_player.ocr import PSM, TesseractBackend, TesseractConfig
from adb_auto_player.util import SummaryGenerator

from ..base import AFKJourneyBase
from ..battle_state import Mode
from ..gui_category import AFKJCategory


class DurasTrialsMixin(AFKJourneyBase):
    """Dura's Trials Mixin."""

    SWEEP_TEMPLATE = "duras_trials/sweep.png"
    SWEEP_MAX_COUNT_TEMPLATE = "duras_trials/max_count.png"
    CURRENT_LIMIT_REACHED_TEMPLATE = "duras_trials/current_limit_reached.png"
    SWEEP_COUNT_SLICE_HEIGHT = 30

    @register_command(
        name="DurasTrials",
        gui=GUIMetadata(
            label="Dura's Trials",
            category=AFKJCategory.GAME_MODES,
        ),
    )
    @register_custom_routine_choice(label="Dura's Trials")
    def push_duras_trials(self) -> None:
        """Push Dura's Trials."""
        self.start_up()
        self.battle_state.mode = Mode.DURAS_TRIALS
        self.navigate_to_duras_trials_screen()

        try:
            if self.settings.duras_trials.force_sweep or self._is_max_level():
                self._handle_sweep()
            else:
                self._handle_dura_screen()
        except AutoPlayerWarningError as e:
            logging.warning(f"{e}")
        except AutoPlayerError as e:
            logging.error(f"{e}")

    def _is_max_level(self) -> bool:
        """Check if current trial has reached its maximum level."""
        result = (
            self.game_find_template_match(self.CURRENT_LIMIT_REACHED_TEMPLATE)
            is not None
        )
        if result:
            logging.info("Current limit reached, max level.")
        return result

    def _handle_sweep(self) -> None:
        """Sweep Dura's Trials for daily rewards."""
        dura_state = self._dura_resolve_state()
        if dura_state.template != "duras_trials/sweep.png":
            logging.info("Sweep not available; stage not yet cleared.")
            return

        available = self._read_sweep_count(dura_state)
        if available <= 0:
            return

        logging.info("Tapping Sweep...")
        self.tap(dura_state)
        sleep(2)

        # Set max sweep count.
        max_btn = self.game_find_template_match(self.SWEEP_MAX_COUNT_TEMPLATE)
        if max_btn:
            logging.info("Setting sweep count to max.")
            self.tap(max_btn)
            sleep(1)
            sweep_count = available
        else:
            logging.warning("Max count button not found.")
            sweep_count = 1

        # Confirm sweep.
        sweep_confirm = self.game_find_template_match(self.SWEEP_TEMPLATE)
        if sweep_confirm:
            self.tap(sweep_confirm)
            sleep(2)

        # Dismiss Sweep Complete popup.
        self._dismiss_sweep_result()

        SummaryGenerator.increment("Dura's Trials", "Swept", sweep_count)
        logging.info("Dura's Trials sweep completed (%d times).", sweep_count)

    def _dismiss_sweep_result(self) -> None:
        """Dismiss the Sweep Complete popup."""
        if not self.handle_popup_messages():
            tap_to_close = self.game_find_template_match("tap_to_close.png")
            if tap_to_close:
                self.tap(tap_to_close)
                sleep(1)

    # Bright pixel ratio threshold: below this the count text is dimmed (0 tokens).
    SWEEP_COUNT_BRIGHT_THRESHOLD = 0.05

    def _read_sweep_count(self, sweep_button: TemplateMatchResult) -> int:
        """Read available sweep count from text below the Sweep button (e.g. '6/1').

        Uses brightness detection to identify 0 tokens (dimmed text) and OCR
        to read the actual count when tokens are available (bright white text).

        Args:
            sweep_button: The Sweep button match result.

        Returns:
            The available sweep count, or 0 if no tokens available.
        """
        screenshot = self.get_screenshot()

        x = sweep_button.box.top_left.x
        y = sweep_button.box.top_left.y + sweep_button.box.height
        w = sweep_button.box.width
        h = self.SWEEP_COUNT_SLICE_HEIGHT

        # Skip left half to avoid token icon interfering with OCR.
        icon_offset = w // 2
        crop = screenshot[y : y + h, x + icon_offset : x + w]
        if crop.size == 0:
            logging.warning("Sweep count crop is empty, defaulting to 1.")
            return 1

        gray = Color.to_grayscale(crop, ColorFormat.BGR)

        # Check brightness: 0 tokens shows dimmed text (low bright pixel ratio).
        bright_ratio = np.sum(gray > 200) / gray.size
        if bright_ratio < self.SWEEP_COUNT_BRIGHT_THRESHOLD:
            logging.info("No sweep tokens available (bright_ratio=%.3f).", bright_ratio)
            return 0

        _, thresholded = cv2.threshold(
            gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU
        )

        ocr = TesseractBackend(config=TesseractConfig(psm=PSM.SINGLE_LINE))
        text = ocr.extract_text(thresholded)
        match = re.search(r"(\d+)/(\d+)", text.strip())
        if match:
            count = int(match.group(1))
            logging.info("Sweep count: %s", text.strip())
            return count

        logging.warning(
            "Could not parse sweep count from '%s', defaulting to 1.", text.strip()
        )
        return 1

    def _dura_resolve_state(self) -> TemplateMatchResult:
        while True:
            result = self.wait_for_any_template(
                templates=[
                    "battle/records.png",
                    "duras_trials/battle.png",
                    "duras_trials/sweep.png",
                    "guide/close.png",
                    "guide/next.png",
                    "duras_trials/continue_gray.png",
                ],
            )

            match result.template:
                case "guide/close.png" | "guide/next.png":
                    self._handle_guide_popup()
                case _:
                    break
        return result

    def _handle_dura_screen(self) -> None:
        count = 0

        def handle_duras_pre_battle() -> bool:
            """Handle pre battle steps in normal mode.

            Returns:
                True to continue; False to abort.
            """
            dura_state_result = self._dura_resolve_state()
            match dura_state_result.template:
                case "duras_trials/sweep.png":
                    logging.info("Dura's Trials already cleared")
                    return False
                case "duras_trials/battle.png":
                    self.tap(dura_state_result)
                    sleep(2)
                case "battle/records.png":
                    # No action needed.
                    pass
            return True

        def handle_duras_post_battle() -> bool:
            """Handle post battle actions for normal mode.

            Returns:
                True if the trial is complete, or False to continue pushing battles.
            """
            _ = self.wait_for_any_template(
                templates=[
                    "duras_trials/first_clear_bottom_half.png",
                    "duras_trials/sweep.png",
                ],
                crop_regions=CropRegions(left=0.3, right=0.3, top=0.6, bottom=0.3),
            )
            next_button = self.game_find_template_match(
                template="next.png", crop_regions=CropRegions(left=0.6, top=0.9)
            )
            nonlocal count
            count += 1
            logging.info(f"Dura's Trials cleared: {count}")
            SummaryGenerator.increment("Dura's Trials", "Cleared")
            if next_button is not None:
                self.tap(next_button)
                self.tap(next_button)
                sleep(3)
                return False  # Continue battle loop
            else:
                logging.info("Dura's Trials completed")
                return True  # End loop

        while True:
            if not handle_duras_pre_battle():
                return

            if self._handle_battle_screen(
                self.settings.duras_trials.use_suggested_formations,
            ):
                if handle_duras_post_battle():
                    return
                continue

            logging.info("Dura's Trials failed")
            return
