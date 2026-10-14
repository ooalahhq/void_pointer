"""Camera and gesture settings adapted from the Jarvis tracker."""
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MODEL_PATH = Path(__file__).resolve().parent.parent/'assets'/'models'/'hand_landmarker.task'


@dataclass
class CameraConfig:
    index: int = 0
    source_url: str | None = None
    width: int = 640
    height: int = 480
    model_path: Path = DEFAULT_MODEL_PATH
    mirror: bool = True
    max_fps: float = 30
    # Independent comfortable regions, each mapped to the entire arena.
    regions: tuple = ((.06, .10, .47, .85), (.53, .10, .94, .85))
    stale_after: float = .65
    loss_grace: float = .25


@dataclass
class GestureConfig:
    pinch_on: float = .32
    pinch_off: float = .45
    debounce: float = .06
    hold_time: float = .6
    hand_lost_grace: float = .25
    palm_hold: float = .3
    palm_cooldown: float = .4
    palm_max_motion: float = .05
    victory_hold: float = .3
    victory_grace: float = .1
    neutral_hold: float = .12
    smooth_min_alpha: float = .18
    smooth_max_alpha: float = .75
    smooth_speed_px: float = 900
    dead_zone_px: float = 2.5
