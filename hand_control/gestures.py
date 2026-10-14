"""Gesture interpreter: hand measurements + monotonic timestamps -> one-shot events.

State machine (one hand):

    NO_HAND --landmarks--> HAND --pinch < ON for `debounce`--> PINCH
                            ^                                    |  held >= hold_time
                            |                                    v
                            +--pinch > OFF for `debounce`---- HELD (pinch_held fired once)

* `pinch_started` fires once when a pinch begins, `pinch_held` at most once per
  pinch (a hold is an extension of the same pinch, never a second click), and
  `pinch_released` once when it ends (with `held` telling whether it was a hold).
* Hysteresis: a pinch starts below `pinch_on` and only ends above `pinch_off`,
  so a ratio wobbling around a single threshold cannot chatter.
* Short tracking dropouts (< `hand_lost_grace`) are ignored entirely; a longer
  loss cancels an active pinch (released with cancelled=True) and emits hand_lost.
* `palm_back`: open palm held still for `palm_hold` seconds, then a cooldown;
  the palm must close before it can fire again.
* ✌️ (index + middle up): `victory_started` once the pose is steady, `victory_fired`
  after `victory_hold` seconds (once per pose), `victory_cancelled` if the pose ends
  (longer than `victory_grace`), a pinch starts or the hand is lost before that.

All timing uses the sample timestamps (time.monotonic()), never frame counts.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from .config import GestureConfig


@dataclass(frozen=True)
class HandSample:
    t: float                    # time.monotonic() when the frame was captured
    present: bool
    x: float = 0.5              # pointer landmark, normalised image coords (0..1, mirrored)
    y: float = 0.5
    pinch: float = 1.0          # thumb-index distance / hand size
    open_palm: bool = False
    # 21 (x, y, z) landmarks, normalised & mirrored like x/y; used only to draw the hand hologram
    landmarks: tuple[tuple[float, float, float], ...] | None = None
    victory: bool = False       # ✌️ index + middle extended, ring + pinky curled


class GestureType(str, Enum):
    HAND_FOUND = "hand_found"
    HAND_LOST = "hand_lost"
    PINCH_STARTED = "pinch_started"
    PINCH_HELD = "pinch_held"
    PINCH_RELEASED = "pinch_released"
    PALM_BACK = "palm_back"
    VICTORY_STARTED = "victory_started"
    VICTORY_FIRED = "victory_fired"
    VICTORY_CANCELLED = "victory_cancelled"


@dataclass(frozen=True)
class GestureEvent:
    type: GestureType
    t: float
    held: bool = False          # PINCH_RELEASED: the pinch had reached "held"
    cancelled: bool = False     # PINCH_RELEASED: ended by tracking loss, not by opening fingers
    duration: float = 0.0


class GestureInterpreter:
    def __init__(self, cfg: GestureConfig | None = None):
        self.cfg = cfg or GestureConfig()
        self.reset()

    def reset(self) -> None:
        self.present = False
        self.pinching = False
        self.held = False
        self._lost_since: float | None = None
        self._pinch_t0 = 0.0
        self._on_since: float | None = None
        self._off_since: float | None = None
        self._palm_since: float | None = None
        self._palm_anchor = (0.0, 0.0)
        self._palm_fired = False
        self._cooldown_until = -math.inf
        self.victory = False            # ✌️ hold in progress (or fired and still held)
        self._v_fired = False
        self._v_t0 = 0.0
        self._v_on_since: float | None = None
        self._v_off_since: float | None = None
        self._now = 0.0
        self.last_sample: HandSample | None = None

    # ---- progress values for the HUD (0..1) ----
    def hold_progress(self) -> float:
        if not self.pinching:
            return 0.0
        if self.held:
            return 1.0
        return min(1.0, (self._now - self._pinch_t0) / self.cfg.hold_time)

    def palm_progress(self) -> float:
        if self._palm_since is None or self._palm_fired or self._now < self._cooldown_until:
            return 0.0
        return min(1.0, (self._now - self._palm_since) / self.cfg.palm_hold)

    def victory_progress(self) -> float:
        if not self.victory:
            return 0.0
        if self._v_fired:
            return 1.0
        return min(1.0, (self._now - self._v_t0) / self.cfg.victory_hold)

    def _end_victory(self, now: float) -> list[GestureEvent]:
        was, fired = self.victory, self._v_fired
        self.victory = self._v_fired = False
        self._v_on_since = self._v_off_since = None
        if was and not fired:
            return [GestureEvent(GestureType.VICTORY_CANCELLED, now)]
        return []

    @property
    def tracking_lost(self) -> bool:
        """Hand currently missing but still inside the grace period."""
        return self.present and self._lost_since is not None

    def update(self, s: HandSample) -> list[GestureEvent]:
        cfg = self.cfg
        now = s.t
        self._now = now
        events: list[GestureEvent] = []

        if not s.present:
            # Do not complete a pending gesture using time spent without a hand.
            self._on_since = self._off_since = self._palm_since = self._v_on_since = None
            if self.victory and not self._v_fired:
                events += self._end_victory(now)
            if self.present:
                if self._lost_since is None:
                    self._lost_since = now
                if now - self._lost_since >= cfg.hand_lost_grace:
                    if self.pinching:
                        events.append(GestureEvent(GestureType.PINCH_RELEASED, now, held=self.held,
                                                   cancelled=True, duration=now - self._pinch_t0))
                    events += self._end_victory(now)
                    events.append(GestureEvent(GestureType.HAND_LOST, now))
                    cooldown = self._cooldown_until
                    self.reset()
                    self._cooldown_until = cooldown
                    self._now = now
            return events

        self._lost_since = None
        self.last_sample = s
        if not self.present:
            self.present = True
            events.append(GestureEvent(GestureType.HAND_FOUND, now))

        # ---- pinch with hysteresis + time debounce ----
        if not self.pinching:
            if s.pinch < cfg.pinch_on:
                if self._on_since is None:
                    self._on_since = now
                if now - self._on_since >= cfg.debounce:
                    self.pinching, self.held = True, False
                    self._pinch_t0 = now
                    self._off_since = None
                    self._palm_since = None
                    events += self._end_victory(now)
                    events.append(GestureEvent(GestureType.PINCH_STARTED, now))
            else:
                self._on_since = None
        else:
            if s.pinch > cfg.pinch_off:
                if self._off_since is None:
                    self._off_since = now
                if now - self._off_since >= cfg.debounce:
                    events.append(GestureEvent(GestureType.PINCH_RELEASED, now, held=self.held,
                                               duration=now - self._pinch_t0))
                    self.pinching = self.held = False
                    self._on_since = None
            else:
                self._off_since = None
                if not self.held and now - self._pinch_t0 >= cfg.hold_time:
                    self.held = True
                    events.append(GestureEvent(GestureType.PINCH_HELD, now,
                                               duration=now - self._pinch_t0))

        # ---- ✌️ held -> open for real ----
        if self.pinching:
            pass
        elif s.victory:
            self._v_off_since = None
            if not self.victory:
                if self._v_on_since is None:
                    self._v_on_since = now
                if now - self._v_on_since >= cfg.debounce:
                    self.victory, self._v_fired, self._v_t0 = True, False, now
                    events.append(GestureEvent(GestureType.VICTORY_STARTED, now))
        elif self.victory:
            if self._v_off_since is None:
                self._v_off_since = now
            if now - self._v_off_since >= cfg.victory_grace:
                events += self._end_victory(now)
        else:
            self._v_on_since = None
        if s.victory and self.victory and not self._v_fired and now - self._v_t0 >= cfg.victory_hold:
            self._v_fired = True
            events.append(GestureEvent(GestureType.VICTORY_FIRED, now,
                                       duration=now - self._v_t0))

        # ---- open palm held still -> back ----
        if s.open_palm and not self.pinching:
            if self._palm_since is None:
                self._palm_since, self._palm_anchor = now, (s.x, s.y)
            elif math.dist((s.x, s.y), self._palm_anchor) > cfg.palm_max_motion:
                self._palm_since, self._palm_anchor = now, (s.x, s.y)   # moved: restart timer
            elif (not self._palm_fired and now - self._palm_since >= cfg.palm_hold
                  and now >= self._cooldown_until):
                self._palm_fired = True
                self._cooldown_until = now + cfg.palm_cooldown
                events.append(GestureEvent(GestureType.PALM_BACK, now))
        else:
            self._palm_since = None
            self._palm_fired = False
        return events
