"""Ownership, mapping, calibration and gesture actions; no pygame or camera I/O.

PointerFilter and map_to_screen are adapted from Jarvis interaction.py.
"""
from dataclasses import dataclass
import math

from .config import CameraConfig, GestureConfig
from .gestures import GestureInterpreter, GestureType


def map_to_screen(x, y, region):
    x0, y0, x1, y1 = region
    return (max(0, min(1, (x-x0)/max(1e-6, x1-x0))),
            max(0, min(1, (y-y0)/max(1e-6, y1-y0))))


class PointerFilter:
    def __init__(self, cfg):
        self.cfg = cfg
        self.reset()

    def reset(self):
        self.pos = self.t = None

    def update(self, x, y, t):
        if self.pos is None:
            self.pos, self.t = (x, y), t
            return self.pos
        distance = math.dist((x, y), self.pos)
        dt = max(.001, t-self.t)
        self.t = t
        if distance<self.cfg.dead_zone_px:return self.pos
        k = min(1, distance/dt/self.cfg.smooth_speed_px)
        alpha = self.cfg.smooth_min_alpha+(self.cfg.smooth_max_alpha-self.cfg.smooth_min_alpha)*k
        self.pos = tuple(old+(new-old)*alpha for old,new in zip(self.pos,(x,y)))
        return self.pos


@dataclass
class Owner:
    pos: tuple
    t: float
    velocity: tuple = (0, 0)
    handedness: str = ''


class HandOwnership:
    """Soft temporal matching; every valid detection is assigned to a player.

    Two initial hands are ordered left/right without a mandatory center line.
    Once acquired, identity follows palm motion rather than changing with the
    camera half or detector order. No distance cutoff rejects a fast hand.
    """
    def __init__(self):self.reset()
    def reset(self):self.owners = [None, None]

    @staticmethod
    def anchor(hand):
        sample = hand.sample
        if sample.landmarks:
            return tuple(sum(sample.landmarks[i][axis] for i in (0,5,9,13,17))/5 for axis in (0,1))
        return (sample.x, sample.y)

    def assign(self, hands, t):
        hands = tuple(hands[:2])
        if not hands:return (None,None)
        def cost(slot, index):
            hand = hands[index]
            pos = self.anchor(hand)
            owner = self.owners[slot]
            if owner is None:
                return math.dist(pos,(.25 if slot==0 else .75,.5))+.05
            gap = max(0, t-owner.t)
            horizon = min(gap,.15) if gap<.4 else 0
            predicted = tuple(p+v*horizon for p,v in zip(owner.pos,owner.velocity))
            distance = min(math.dist(predicted,pos),math.dist(owner.pos,pos))
            mismatch = .04 if owner.handedness and hand.score>.8 and owner.handedness!=hand.handedness else 0
            continuity = .15*max(0,1-gap/1.2)
            return distance+mismatch-continuity
        if len(hands)==2:
            if all(owner is None for owner in self.owners):
                chosen=tuple(sorted(range(2),key=lambda index:self.anchor(hands[index])[0]))
            else:
                chosen=min(((0,1),(1,0)),key=lambda assignment:sum(cost(slot,index) for slot,index in enumerate(assignment)))
        else:
            if all(owner is None for owner in self.owners):
                slot=0 if hands[0].sample.x<.5 else 1
            else:slot=min(range(2),key=lambda slot:cost(slot,0))
            chosen=(0,None) if slot==0 else (None,0)
        assigned = []
        for slot,index in enumerate(chosen):
            if index is None:
                assigned.append(None)
                continue
            hand = hands[index]
            pos = self.anchor(hand)
            owner = self.owners[slot]
            velocity = (0,0)
            if owner and 0<t-owner.t<.3:
                velocity = tuple(max(-2,min(2,(new-old)/(t-owner.t))) for old,new in zip(owner.pos,pos))
            self.owners[slot] = Owner(pos,t,velocity,hand.handedness if hand.score>.8 else '')
            assigned.append(hand)
        return tuple(assigned)


class GestureGate:
    """Require a neutral pointing pose after startup, dropout, reset or mode switch."""
    def __init__(self, cfg):
        self.cfg = cfg
        self.reset()

    def reset(self):
        self.interpreter = GestureInterpreter(self.cfg)
        self.armed = False
        self.neutral_since = None
        self.recovering = False

    def suspend(self):
        if self.recovering:return
        # Keep acquisition state, discard unfinished gestures, and require a
        # released pose before a new skill. Brief misses do not unbind a hand.
        self.interpreter = GestureInterpreter(self.cfg)
        self.neutral_since = None
        self.recovering = True

    def update(self, sample):
        if not sample.present:
            self.reset()
            return []
        if not self.armed or self.recovering:
            neutral = sample.pinch>self.cfg.pinch_off and not sample.open_palm and not sample.victory
            if not neutral:
                self.neutral_since = None
            elif self.neutral_since is None:
                self.neutral_since = sample.t
            elif sample.t-self.neutral_since>=self.cfg.neutral_hold:
                self.armed = True
                self.recovering = False
            return []
        events = self.interpreter.update(sample)
        return [event.type for event in events]


@dataclass
class ControlFrame:
    targets: tuple = (None, None)
    actions: tuple = ()
    tracked: tuple = (False, False)
    held: tuple = (False, False)


class HandControls:
    def __init__(self, tracker, arena, camera=None, gesture=None):
        self.tracker = tracker
        self.arena = tuple(arena)
        self.camera = camera or CameraConfig()
        self.gesture = gesture or GestureConfig()
        self.regions = list(self.camera.regions)
        self.ownership = HandOwnership()
        self.calibrating = False
        self.reset()

    def reset(self, rebind=False):
        if rebind:self.ownership.reset()
        self.gates = [GestureGate(self.gesture) for _ in range(2)]
        self.filters = [PointerFilter(self.gesture) for _ in range(2)]
        self.last_sequence = -1
        self.last_t = -math.inf
        self.targets = [None,None]
        self.tracked = [False,False]
        self.raw = [None,None]
        self.seen_at = [-math.inf,-math.inf]
        self.held = [False,False]
        self.calibration_points = [[],[]]
        self.calibration_regions = list(self.regions)
        self.calibrating = False
        self.last_frame = None

    def start_calibration(self):
        self.reset()
        self.calibrating = True

    def calibration_prompt(self):
        prompts = []
        for slot,points in enumerate(self.calibration_points):
            step = 'TOP-LEFT' if not points else 'BOTTOM-RIGHT'
            prompts.append(f'P{slot+1}: '+('DONE' if len(points)==2 else step+' + PINCH'))
        return '   /   '.join(prompts)+'   [C cancel]'

    def _calibrate(self, slot, sample):
        points = self.calibration_points[slot]
        if len(points)==2:return
        points.append((sample.x,sample.y))
        if len(points)==2:
            (ax,ay),(bx,by) = points
            region = (min(ax,bx),min(ay,by),max(ax,bx),max(ay,by))
            if region[2]-region[0]<.15 or region[3]-region[1]<.2:
                points.clear()
            else:self.calibration_regions[slot] = region
        if all(len(points)==2 for points in self.calibration_points):
            self.regions=list(self.calibration_regions)
            self.reset()

    def consume(self, frame, now, active=True):
        actions = []
        if now-frame.t>self.camera.stale_after or frame.t>now+.05:
            self.clear_tracking()
            return ControlFrame()
        if frame.t<=self.last_t:return self.snapshot()
        # Inference stalls cannot complete a gesture across a gap.
        if frame.t-self.last_t>self.camera.stale_after:self.clear_tracking()
        self.last_t = frame.t
        self.last_frame = frame
        assigned = self.ownership.assign(frame.hands,frame.t)
        for slot,hand in enumerate(assigned):
            if hand is None:
                # Freeze player motion immediately, keep the crosshair/filter
                # during a short dropout, and cancel unfinished gestures.
                self.held[slot]=frame.t-self.seen_at[slot]<=self.camera.loss_grace
                self.tracked[slot]=self.held[slot]
                if self.held[slot]:self.gates[slot].suspend()
                else:self.gates[slot].reset()
                if not self.held[slot]:
                    self.targets[slot] = self.raw[slot] = None
                    self.filters[slot].reset()
                continue
            sample = hand.sample
            self.seen_at[slot]=frame.t
            self.tracked[slot]=True;self.held[slot]=False
            self.raw[slot] = sample
            u,v = map_to_screen(sample.x,sample.y,self.regions[slot])
            left,top,width,height = self.arena
            target = self.filters[slot].update(left+8+u*(width-16),top+8+v*(height-16),sample.t)
            self.targets[slot] = target
            if not active and not self.calibrating:
                self.gates[slot].reset()
                continue
            events = self.gates[slot].update(sample)
            if self.calibrating:
                if GestureType.PINCH_STARTED in events:self._calibrate(slot,sample)
            else:
                mapping = {GestureType.PINCH_STARTED:'dash',GestureType.PALM_BACK:'shield',
                           GestureType.VICTORY_FIRED:'pulse'}
                actions.extend((slot,mapping[event]) for event in events if event in mapping)
        return self.snapshot(tuple(actions))

    def snapshot(self, actions=()):
        targets=tuple(None if self.calibrating or self.held[slot] else target
                      for slot,target in enumerate(self.targets))
        return ControlFrame(targets,actions,tuple(self.tracked),tuple(self.held))

    def clear_tracking(self):
        self.targets = [None,None]
        self.tracked = [False,False]
        self.raw = [None,None]
        self.seen_at = [-math.inf,-math.inf]
        self.held = [False,False]
        for gate in self.gates:gate.reset()
        for pointer in self.filters:pointer.reset()

    def poll(self, now, active=True):
        sequence,frame = self.tracker.samples.get()
        if frame is not None and sequence!=self.last_sequence:
            self.last_sequence = sequence
            return self.consume(frame,now,active)
        if now-self.last_t>self.camera.stale_after:self.clear_tracking()
        # A cached blank frame must not extend the grace interval indefinitely.
        for slot,held in enumerate(self.held):
            if held and now-self.seen_at[slot]>self.camera.loss_grace:
                self.held[slot]=False;self.tracked[slot]=False
                self.targets[slot]=self.raw[slot]=None
                self.filters[slot].reset()
        return self.snapshot()
