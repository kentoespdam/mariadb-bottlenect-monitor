"""Edge-triggered State Toggle — fires callbacks only on transitions.

Begins at False per "begin at false every boot" rule (CONTEXT.md).
Supports freeze() for blindness periods — no transitions while frozen.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

log = logging.getLogger(__name__)


class StateToggle:
    """Boolean state that alerts only on false→true or true→false edges.

    Up to one callback per edge type. Freeze prevents any transition.
    """

    def __init__(
        self,
        name: str = "",
        on_up: Callable[[], None] | None = None,
        on_down: Callable[[], None] | None = None,
    ) -> None:
        self._name = name
        self._value = False
        self._frozen = False
        self._on_up = on_up
        self._on_down = on_down

    @property
    def is_set(self) -> bool:
        return self._value

    @property
    def is_frozen(self) -> bool:
        return self._frozen

    def set(self, new: bool) -> None:
        """Transition to new value. Fires callback on edge. No-op if frozen."""
        if self._frozen or new == self._value:
            return
        self._value = new
        if new and self._on_up:
            log.info("StateToggle[%s] UP", self._name)
            self._on_up()
        elif not new and self._on_down:
            log.info("StateToggle[%s] DOWN", self._name)
            self._on_down()

    def freeze(self) -> None:
        self._frozen = True

    def unfreeze(self) -> None:
        self._frozen = False

    def force(self, value: bool) -> None:
        """Set value without firing callbacks. Used for recovery from frozen."""
        self._value = value

    def __bool__(self) -> bool:
        return self._value
