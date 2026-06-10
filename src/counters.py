"""Poll counters: N, K, J, M."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


class _FreezeableCounter:
    """Base for counters that freeze during blindness (N, J)."""

    def __init__(self, threshold: int) -> None:
        self._threshold = threshold
        self._value = 0
        self._frozen = False

    @property
    def value(self) -> int:
        return self._value

    @property
    def satisfied(self) -> bool:
        return self._value >= self._threshold

    def increment(self) -> None:
        if not self._frozen:
            self._value += 1

    def reset(self) -> None:
        if not self._frozen:
            self._value = 0

    def freeze(self) -> None:
        self._frozen = True

    def unfreeze(self) -> None:
        self._frozen = False


class NCounter(_FreezeableCounter):
    """Sustained Bottleneck — counts consecutive over-exit polls."""


class JCounter(_FreezeableCounter):
    """Attribution Blindness — counts consecutive phase-two failures."""


class _SimpleCounter:
    """Base for counters with no freeze behaviour (K, M)."""

    def __init__(self, threshold: int) -> None:
        self._threshold = threshold
        self._value = 0

    @property
    def value(self) -> int:
        return self._value

    @property
    def satisfied(self) -> bool:
        return self._value >= self._threshold

    def increment(self) -> None:
        self._value += 1

    def reset(self) -> None:
        self._value = 0


class KCounter(_SimpleCounter):
    """Monitor Blindness — counts consecutive failed polls."""


class MCounter(_SimpleCounter):
    """Heal Cooldown — counts wall-clock polls since last kill.

    Uses tick() instead of increment() for semantic clarity.
    """

    def tick(self) -> None:
        self._value += 1


def evaluate_hysteresis(threads_running: int, entry: int, exit: int) -> bool | None:
    """Evaluate whether we're in Bottleneck based on hysteresis thresholds."""
    if threads_running > entry:
        return True
    if threads_running <= exit:
        return False
    return None
