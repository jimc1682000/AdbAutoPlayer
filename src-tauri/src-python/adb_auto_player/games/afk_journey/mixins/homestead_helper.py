"""Homestead helper mixin."""

import logging
import math
import os
import re
from time import sleep

import cv2
from adb_auto_player.decorators import register_command, register_custom_routine_choice
from adb_auto_player.exceptions import GameTimeoutError
from adb_auto_player.games.afk_journey.base import AFKJourneyBase
from adb_auto_player.games.afk_journey.gui_category import AFKJCategory
from adb_auto_player.image_manipulation import Color, ColorFormat
from adb_auto_player.models.decorators import GUIMetadata
from adb_auto_player.models.geometry import Point
from adb_auto_player.models.image_manipulation import CropRegions
from adb_auto_player.ocr import PSM, TesseractBackend, TesseractConfig
from adb_auto_player.util import SummaryGenerator


class HomesteadHelperMixin(AFKJourneyBase):
    """Homestead helper mixin."""

    # Templates — homestead main screen.
    HOMESTEAD_OVERVIEW_CHECK_TEMPLATE = "homestead/homestead_overview_check.png"

    # Templates — Requests page.
    REQUESTS_ENTRY_TEMPLATE = "homestead/order_requests.png"
    NAVIGATE_TO_CRAFTING_TEMPLATE = "homestead/missing_item_navigate_to_crafting.png"
    GIVE_UP_TEMPLATE = "homestead/order_page_give_up.png"
    INSUFFICIENT_RESOURCES_TEMPLATE = "homestead/insufficient_resources.png"

    # Templates — homestead.
    HARVEST_ALL_TEMPLATE = "homestead/harvest_all.png"

    # Templates — crafting workshop.
    CRAFTING_DECK_TEMPLATE = "homestead/deck_in_crafting_page.png"
    CRAFTING_X1_TEMPLATE = "homestead/crafting_x1.png"
    CRAFTING_X5_TEMPLATE = "homestead/crafting_x5.png"
    CRAFTING_X10_TEMPLATE = "homestead/crafting_x10.png"

    # Templates — star rewards.
    STAR_REWARDS_INDICATOR_TEMPLATE = "homestead/star_rewards_indicator.png"
    REWARDS_OBTAINED_TEMPLATE = "homestead/rewards_obtained.png"

    # Timeouts.
    REQUESTS_PAGE_TIMEOUT = 10.0
    CRAFTING_PAGE_TIMEOUT = 15.0
    CRAFTING_ANIMATION_WAIT = 7

    # Requests page controls.
    QUICK_SELECT_POINT = Point(540, 1620)

    # Crafting controls.
    CRAFT_ITEM_POINT = Point(530, 1700)
    CRAFTING_STOCK_SLICE = (923, 915, 80, 50)
    CRAFTING_REQUEST_SLICE = (953, 975, 50, 50)

    POPUP_DISMISS_POINT = Point(540, 1800)

    # Processing building controls (Ore Refinery / Lumbermill / Essence Crucible).
    PROCESSING_MAX_TEMPLATE = "homestead/max_count.png"
    PROCESSING_ACTION_BUTTON = Point(564, 1795)

    @register_command(
        name="HomesteadOrdersHelper",
        gui=GUIMetadata(
            label="Homestead Orders Helper",
            category=AFKJCategory.GAME_MODES,
        ),
    )
    @register_custom_routine_choice(label="Homestead Orders Helper")
    def run_homestead_orders(self) -> None:
        """Navigate through NPC requests to craft and fulfill orders."""
        self.start_up()
        self.navigate_to_homestead()

        if not self._enter_requests_page():
            logging.error("Failed to enter Requests page.")
            return

        crafted_total = 0
        harvest_used = False
        processing_used = False
        crafting_failures = 0

        while True:
            if crafting_failures >= 2:
                logging.warning("Crafting failed twice in a row; stopping.")
                break

            if not self._has_homestead_request():
                logging.info("No active request; re-entering Requests page...")
                self.navigate_to_homestead()
                if not self._enter_requests_page() or not self._has_homestead_request():
                    logging.info("No more requests.")
                    break

            self.tap(self.QUICK_SELECT_POINT)
            sleep(2)

            if not self.game_find_template_match(
                template=self.INSUFFICIENT_RESOURCES_TEMPLATE,
            ):
                # Resources sufficient — tap "Delivered" (same position) + dismiss popup.
                logging.info("Resources sufficient; tapping Delivered...")
                self._deliver_order()
                crafting_failures = 0
                # Still on Requests page; loop back to find next Quick Select.
                continue

            navigate_arrow = self.game_find_template_match(
                template=self.NAVIGATE_TO_CRAFTING_TEMPLATE,
            )
            if navigate_arrow is None:
                logging.info(
                    "Insufficient resources with no crafting option; stopping."
                )
                break

            # Insufficient resources — go to workshop and craft.
            logging.info("Insufficient resources; navigating to workshop...")
            crafted, action = self._enter_workshop_and_craft(
                navigate_arrow=navigate_arrow,
                harvest_used=harvest_used,
                processing_used=processing_used,
            )
            if action == "harvest":
                harvest_used = True
            elif action == "processing":
                processing_used = True
            if action is not None:
                # After harvest/processing we're on homestead main screen.
                if not self._enter_requests_page():
                    logging.error("Failed to re-enter Requests page.")
                    break
                continue
            if crafted == 0:
                crafting_failures += 1
            else:
                crafting_failures = 0
            crafted_total += crafted
            # Re-enter Requests page from scratch.
            self.navigate_to_homestead()
            if not self._enter_requests_page():
                logging.error("Failed to re-enter Requests page.")
                break

        # Collect daily star rewards before leaving.
        self.navigate_to_homestead()
        if self._enter_requests_page():
            self.get_star_rewards()

        self._return_to_homestead()
        logging.info("Total items crafted: %d", crafted_total)

    ############################## Requests Page ##############################

    def _enter_requests_page(self) -> bool:
        """Enter the Requests page from the homestead main screen."""
        sleep(1)
        requests_icon = self.game_find_template_match(
            template=self.REQUESTS_ENTRY_TEMPLATE,
        )
        if requests_icon is None:
            return False

        self.tap(requests_icon)
        sleep(2)

        try:
            self.wait_for_template(
                template=self.GIVE_UP_TEMPLATE,
                timeout=self.REQUESTS_PAGE_TIMEOUT,
                timeout_message="Requests page did not load.",
            )
            return True
        except GameTimeoutError:
            return False

    def _harvest_raw_materials(self) -> None:
        """Handle insufficient raw materials during crafting.

        Tap the first '>' to navigate to field, harvest all resources.
        Caller is responsible for re-navigating afterwards.
        """
        navigate_arrow = self.game_find_template_match(
            template=self.NAVIGATE_TO_CRAFTING_TEMPLATE,
        )
        if navigate_arrow is None:
            logging.warning("No navigate arrow found on insufficient resources popup.")
            self.press_back_button()
            sleep(1)
            return

        self.tap(navigate_arrow)
        sleep(3)

        try:
            harvest_btn = self.wait_for_template(
                template=self.HARVEST_ALL_TEMPLATE,
                timeout=self.REQUESTS_PAGE_TIMEOUT,
                timeout_message="Harvest All button not found.",
            )
            logging.info("Harvesting all...")
            self.tap(harvest_btn)
            sleep(3)
        except GameTimeoutError:
            logging.warning("Harvest All button not found.")

    def _produce_at_processing_building(self) -> None:
        """Navigate to a processing building and produce max materials.

        Handles Ore Refinery (Smelt), Lumbermill (Shape),
        and Essence Crucible (Refine). Expects the insufficient resources
        popup with a > arrow to be visible.
        Caller is responsible for re-navigating afterwards.
        """
        navigate_arrow = self.game_find_template_match(
            template=self.NAVIGATE_TO_CRAFTING_TEMPLATE,
        )
        if navigate_arrow is None:
            logging.warning("No navigate arrow found for processing building.")
            self.press_back_button()
            sleep(1)
            return

        self.tap(navigate_arrow)
        sleep(3)

        # Tap >>| to maximize production quantity.
        max_btn = self.game_find_template_match(
            template=self.PROCESSING_MAX_TEMPLATE,
        )
        if max_btn is None:
            logging.warning("Max count button not found in processing building.")
            self.press_back_button()
            sleep(2)
            return

        self.tap(max_btn)
        sleep(1)

        # Tap the green action button (Smelt/Shape/Refine).
        self.tap(self.PROCESSING_ACTION_BUTTON)
        sleep(3)

        # Dismiss Rewards Obtained popup.
        if self.game_find_template_match(template=self.REWARDS_OBTAINED_TEMPLATE):
            self.tap(self.POPUP_DISMISS_POINT)
            sleep(2)

        # Return to homestead main screen.
        self.press_back_button()
        sleep(2)

    def _deliver_order(self) -> None:
        """Tap 'Delivered' button and dismiss the reward popup."""
        sleep(1)
        self.tap(self.QUICK_SELECT_POINT)
        sleep(2)
        # Dismiss full-page reward popup.
        if not self.handle_popup_messages():
            self.tap(self.POPUP_DISMISS_POINT)
            sleep(1)
        SummaryGenerator.increment("Homestead Orders Helper", "Orders Sold")

    def get_star_rewards(self) -> None:
        """Collect available Daily Delivered Star Rewards on the Requests page."""
        logging.info("Checking for daily star rewards...")

        collected = 0
        while True:
            star_indicator = self.game_find_template_match(
                template=self.STAR_REWARDS_INDICATOR_TEMPLATE,
                crop_regions=CropRegions(bottom="80%", right="50%"),
            )
            if star_indicator is None:
                break

            self.tap(star_indicator)
            sleep(2)

            if self.game_find_template_match(
                template=self.REWARDS_OBTAINED_TEMPLATE,
            ):
                collected += 1
                SummaryGenerator.increment(
                    "Homestead Orders Helper", "Star Rewards Collected"
                )
                self.tap(self.POPUP_DISMISS_POINT)
                sleep(1)
            else:
                break

        if collected:
            logging.info("Collected %d star reward(s).", collected)
        else:
            logging.info("No claimable star rewards available.")

    ############################## Workshop Crafting ##############################

    def _enter_workshop_and_craft(
        self,
        *,
        navigate_arrow: object,
        harvest_used: bool = False,
        processing_used: bool = False,
    ) -> tuple[int, str | None]:
        """Navigate from insufficient-resources popup to workshop and craft.

        Returns:
            tuple[int, str | None]: (items crafted, action taken).
            Action is "harvest", "processing", or None.
        """
        self.tap(navigate_arrow)
        sleep(2)

        if not self._wait_for_workshop():
            logging.warning("Workshop did not appear; returning.")
            return 0, None

        multiplier = self._ensure_x10_multiplier()
        return self._craft_until_fulfilled(
            multiplier=multiplier,
            harvest_used=harvest_used,
            processing_used=processing_used,
        )

    def _ensure_x10_multiplier(self) -> int:
        """Ensure crafting multiplier is set to x10.

        Cycle: x1 -> x5 -> x10 -> x1. Detects current state and taps
        the required number of times to reach x10.

        Returns:
            int: The active multiplier (1, 5, or 10).
        """
        if self.game_find_template_match(template=self.CRAFTING_X10_TEMPLATE):
            logging.debug("Multiplier already x10.")
            return 10

        x1_btn = self.game_find_template_match(template=self.CRAFTING_X1_TEMPLATE)
        if x1_btn is not None:
            # x1 -> x5 -> x10 (tap twice)
            logging.info("Multiplier is x1; switching to x10.")
            self.tap(x1_btn)
            sleep(1)
            self.tap(x1_btn)
            sleep(1)
            return 10

        x5_btn = self.game_find_template_match(template=self.CRAFTING_X5_TEMPLATE)
        if x5_btn is not None:
            # x5 -> x10 (tap once)
            logging.info("Multiplier is x5; switching to x10.")
            self.tap(x5_btn)
            sleep(1)
            return 10

        logging.warning("Could not detect multiplier; defaulting to x1.")
        return 1

    def _craft_until_fulfilled(
        self,
        *,
        multiplier: int = 1,
        harvest_used: bool = False,
        processing_used: bool = False,
    ) -> tuple[int, str | None]:
        """Craft items in the workshop until Stock meets Request.

        Returns:
            tuple[int, str | None]: (items crafted, action taken).
            Action is "harvest", "processing", or None.
        """
        ocr = TesseractBackend(config=TesseractConfig(psm=PSM.SINGLE_LINE))

        stock_count, request_count = self._get_crafting_counts(ocr)
        if stock_count is None or request_count is None:
            logging.warning(
                "OCR failed for crafting counts (stock=%s, request=%s); skipping.",
                stock_count,
                request_count,
            )
            return 0, None

        needed = request_count - stock_count
        if needed <= 0:
            logging.info("Stock already meets request; no crafting needed.")
            return 0, None

        taps = math.ceil(needed / multiplier)
        total_craft = taps * multiplier
        logging.info(
            "Crafting %d items in %d taps x%d"
            " (stock=%d, request=%d, craft=%d, estimated_stock=%d).",
            needed,
            taps,
            multiplier,
            stock_count,
            request_count,
            total_craft,
            stock_count + total_craft,
        )

        for i in range(taps):
            self.tap(self.CRAFT_ITEM_POINT)
            sleep(2)

            # Check if insufficient raw materials popup appeared.
            if self.game_find_template_match(
                template=self.INSUFFICIENT_RESOURCES_TEMPLATE,
            ):
                actual_crafted = i * multiplier
                SummaryGenerator.increment(
                    "Homestead Orders Helper", "Items Crafted", actual_crafted
                )

                # Count > arrows: 2 = harvest + building, 1 = building only.
                arrows = self.find_all_template_matches(
                    template=self.NAVIGATE_TO_CRAFTING_TEMPLATE,
                )
                arrow_count = len(arrows) if arrows else 0

                if arrow_count >= 2 and not harvest_used:
                    logging.info("Raw materials insufficient; harvesting...")
                    self._harvest_raw_materials()
                    return actual_crafted, "harvest"

                if not processing_used:
                    logging.info(
                        "Processed materials insufficient; "
                        "navigating to processing building..."
                    )
                    self._produce_at_processing_building()
                    return actual_crafted, "processing"

                logging.info(
                    "Insufficient resources; harvest and processing already used."
                )
                return actual_crafted, None

            if not self._wait_for_crafting_ready():
                logging.warning("Crafting blocked (e.g. stamina depleted); stopping.")
                return 0, None

        actual_crafted = taps * multiplier
        SummaryGenerator.increment(
            "Homestead Orders Helper", "Items Crafted", actual_crafted
        )
        return actual_crafted, None

    def _wait_for_crafting_ready(self, max_attempts: int = 10) -> bool:
        """Wait for crafting animation to complete.

        Returns:
            bool: True if crafting deck reappeared, False if timed out.
        """
        sleep(self.CRAFTING_ANIMATION_WAIT)

        for _ in range(max_attempts):
            if self.game_find_template_match(
                template=self.CRAFTING_DECK_TEMPLATE,
            ):
                return True
            sleep(3)
        logging.warning("Crafting deck not detected after %ds.", max_attempts * 3)
        # Dismiss possible blocking popup (e.g. Stamina Bundle purchase page).
        self.tap(self.POPUP_DISMISS_POINT)
        sleep(2)
        return False

    def _wait_for_workshop(self) -> bool:
        """Wait for the crafting workshop, dismissing popups each iteration."""
        max_attempts = int(self.CRAFTING_PAGE_TIMEOUT / 2)
        for _ in range(max_attempts):
            if self.game_find_template_match(template=self.CRAFTING_DECK_TEMPLATE):
                return True
            self.handle_popup_messages()
            sleep(2)
        return False

    def _has_homestead_request(self) -> bool:
        """Check if we are on the Requests page with an active request.

        Uses the Give Up template as a proxy — it is only visible when
        an NPC request is displayed (and Quick Select is available).
        """
        return self.game_find_template_match(template=self.GIVE_UP_TEMPLATE) is not None

    ############################## Helper Functions ##############################

    def _is_homestead_page(self) -> bool:
        """Check if currently on the homestead main screen."""
        return (
            self.game_find_template_match(template=self.REQUESTS_ENTRY_TEMPLATE)
            is not None
            or self.game_find_template_match(
                template=self.HOMESTEAD_OVERVIEW_CHECK_TEMPLATE
            )
            is not None
        )

    def _return_to_homestead(self, max_attempts: int = 10) -> None:
        """Press back repeatedly until reaching the homestead main screen."""
        for _ in range(max_attempts):
            if self._is_homestead_page():
                return
            self.press_back_button()
            sleep(2)
        logging.warning(
            "Failed to return to homestead after %d attempts.", max_attempts
        )

    def _get_crafting_counts(
        self,
        ocr: TesseractBackend,
    ) -> tuple[int | None, int | None]:
        screenshot = self.get_screenshot()
        stock_count = self._ocr_number_from_slice(
            screenshot,
            self.CRAFTING_STOCK_SLICE,
            ocr,
        )
        request_count = self._ocr_number_from_slice(
            screenshot,
            self.CRAFTING_REQUEST_SLICE,
            ocr,
        )
        if stock_count is None or request_count is None:
            self._save_debug_crops(screenshot)
        return stock_count, request_count

    def _save_debug_crops(self, screenshot) -> None:
        """Save debug images when OCR fails on crafting counts."""
        try:
            os.makedirs("debug", exist_ok=True)
            cv2.imwrite("debug/homestead_crafting_screenshot.png", screenshot)
            sx, sy, sw, sh = self.CRAFTING_STOCK_SLICE
            cv2.imwrite(
                "debug/homestead_crafting_stock_crop.png",
                screenshot[sy : sy + sh, sx : sx + sw],
            )
            rx, ry, rw, rh = self.CRAFTING_REQUEST_SLICE
            cv2.imwrite(
                "debug/homestead_crafting_request_crop.png",
                screenshot[ry : ry + rh, rx : rx + rw],
            )
            logging.debug("Debug images saved to debug/ directory.")
        except Exception as e:
            logging.debug("Failed to save debug images: %s", e)

    def _ocr_number_from_slice(
        self,
        image,
        region: tuple[int, int, int, int],
        ocr: TesseractBackend,
    ) -> int | None:
        x, y, width, height = region
        crop = image[y : y + height, x : x + width]
        if crop.size == 0:
            return None
        gray = Color.to_grayscale(crop, ColorFormat.BGR)
        _, thresholded = cv2.threshold(
            gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU
        )
        text = ocr.extract_text(thresholded)
        digits = re.findall(r"\d+", text)
        if not digits:
            return None
        return int("".join(digits))
