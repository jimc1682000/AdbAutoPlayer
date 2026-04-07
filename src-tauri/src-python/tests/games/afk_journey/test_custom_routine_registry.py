"""Tests for AFK Journey custom routine registration and mixin instantiation."""

import pytest

# Importing the mixins triggers decorator registration.
from adb_auto_player.games.afk_journey.mixins.afk_stages import AFKStagesMixin  # noqa: F401
from adb_auto_player.games.afk_journey.mixins.arcane_labyrinth import (
    ArcaneLabyrinthMixin,  # noqa: F401
)
from adb_auto_player.games.afk_journey.mixins.arena import ArenaMixin  # noqa: F401
from adb_auto_player.games.afk_journey.mixins.dailies import DailiesMixin
from adb_auto_player.games.afk_journey.mixins.dream_realm import (
    DreamRealmMixin,  # noqa: F401
)
from adb_auto_player.games.afk_journey.mixins.duras_trials import (
    DurasTrialsMixin,  # noqa: F401
)
from adb_auto_player.games.afk_journey.mixins.legend_trial import (
    SeasonLegendTrial,  # noqa: F401
)
from adb_auto_player.registries import CUSTOM_ROUTINE_REGISTRY

MODULE_KEY = "afk_journey"

EXPECTED_LABELS = {
    # Pre-existing
    "AFK Stages",
    "Season AFK Stages",
    "Arcane Labyrinth",
    "Dura's Trials",
    "Season Legend Trial",
    # New: DailiesMixin
    "Claim Daily Rewards",
    "Buy Emporium",
    "Single Pull",
    "Claim Rewards",
    "Raise Affinity",
    "Swap Essences",
    # New: other mixins
    "Dream Realm",
    "Arena",
}


class TestCustomRoutineRegistry:
    """Verify all expected custom routine choices are registered."""

    def test_afk_journey_module_registered(self) -> None:
        assert MODULE_KEY in CUSTOM_ROUTINE_REGISTRY

    def test_all_expected_labels_registered(self) -> None:
        registered = set(CUSTOM_ROUTINE_REGISTRY[MODULE_KEY].keys())
        missing = EXPECTED_LABELS - registered
        assert not missing, f"Missing custom routine labels: {missing}"

    @pytest.mark.parametrize("label", sorted(EXPECTED_LABELS))
    def test_each_label_has_callable_func(self, label: str) -> None:
        entry = CUSTOM_ROUTINE_REGISTRY[MODULE_KEY].get(label)
        assert entry is not None, f"Label '{label}' not in registry"
        assert callable(entry.func), f"Label '{label}' func is not callable"


class TestDailiesMixinInstantiation:
    """Verify DailiesMixin can be instantiated after ABC removal."""

    def test_instantiation_does_not_raise(self) -> None:
        instance = DailiesMixin()
        assert instance is not None

    def test_has_registered_methods(self) -> None:
        instance = DailiesMixin()
        methods = [
            "claim_daily_rewards",
            "buy_emporium",
            "single_pull",
            "claim_hamburger",
            "raise_hero_affinity",
            "swap_essences",
            "run_dailies",
        ]
        for method in methods:
            assert hasattr(instance, method), f"Missing method: {method}"
            assert callable(getattr(instance, method)), f"{method} not callable"
