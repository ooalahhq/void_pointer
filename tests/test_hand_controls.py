import os
os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['SDL_AUDIODRIVER'] = 'dummy'

from types import SimpleNamespace
import unittest
from unittest.mock import patch

import main as game
from hand_control.config import CameraConfig, GestureConfig
from hand_control.gestures import HandSample, GestureType
from hand_control.input import HandControls, HandOwnership, GestureGate, map_to_screen
from hand_control.tracker import HandFrame, TrackedHand, LatestSlot, HandTracker, measure_hand


def hand(t, x, y=.5, pinch=1, palm=False, victory=False, label='Right', wrist=None):
    points=[(x,y,0)]*21
    if wrist is not None:
        for index in (0,5,9,13,17):points[index]=(wrist[0],wrist[1],0)
    return TrackedHand(HandSample(t,True,x,y,pinch,palm,tuple(points),victory),label,.99)


class HandControlTests(unittest.TestCase):
    def setUp(self):
        self.tracker=SimpleNamespace(samples=LatestSlot(),paused=False,status=('test','ok'))
        self.controls=HandControls(self.tracker,game.ARENA)

    def frame(self,t,*hands,active=True):
        return self.controls.consume(HandFrame(t,hands),t,active)

    def arm(self):
        for t in (0,.07,.15,.2):self.frame(t,hand(t,.25),hand(t,.75))

    def test_initial_ownership_and_reordered_same_handedness(self):
        ownership=HandOwnership()
        p1,p2=hand(0,.2),hand(0,.8)
        self.assertEqual(ownership.assign((p2,p1),0),(p1,p2))
        p1,p2=hand(.05,.22),hand(.05,.78)
        self.assertEqual(ownership.assign((p2,p1),.05),(p1,p2))
        self.assertEqual(ownership.assign((p2,),.1),(None,p2))

    def test_two_hands_acquire_even_when_both_palms_are_left_of_center(self):
        ownership=HandOwnership()
        p1,p2=hand(0,.1),hand(0,.4)
        self.assertEqual(ownership.assign((p2,p1),0),(p1,p2))

    def test_fast_p1_detection_is_not_rejected_by_distance_or_center_line(self):
        ownership=HandOwnership()
        ownership.assign((hand(0,.25),hand(0,.8)),0)
        moved=hand(.05,.6,.2,label='Left')
        p2=hand(.05,.81)
        self.assertEqual(ownership.assign((p2,moved),.05),(moved,p2))
        self.assertEqual(ownership.assign((moved,),.1),(moved,None))

    def test_reacquired_hand_keeps_its_owner_after_long_dropout(self):
        ownership=HandOwnership()
        ownership.assign((hand(0,.25),hand(0,.75)),0)
        # Both crossed during an observable trajectory before one dropped out.
        for i in range(1,7):
            t=i*.1
            ownership.assign((hand(t,.25+i*.08),hand(t,.75-i*.08)),t)
        ownership.assign((hand(.7,.27),),.7)
        p1=hand(2,.73)
        p2=hand(2,.27)
        self.assertEqual(ownership.assign((p2,p1),2),(p1,p2))

    def test_wrist_assignment_survives_fingertip_gesture_motion(self):
        ownership=HandOwnership()
        ownership.assign((hand(0,.25),hand(0,.75)),0)
        p1=hand(.05,.7,wrist=(.26,.5))
        p2=hand(.05,.3,wrist=(.74,.5))
        self.assertEqual(ownership.assign((p2,p1),.05),(p1,p2))

    def test_velocity_prediction_preserves_crossing_owners(self):
        ownership=HandOwnership()
        for i in range(7):
            t=i*.1
            p1,p2=hand(t,.2+i*.1),hand(t,.8-i*.1)
            # At the exact overlap there is no distinct visual identity. Keep detector order.
            detected=(p2,p1) if i!=3 else (p1,p2)
            assigned=ownership.assign(detected,t)
            if i!=3:self.assertEqual(assigned,(p1,p2))

    def test_pointer_mapping_smoothing_and_arena_bounds(self):
        result=self.frame(0,hand(0,.06,.1),hand(0,.94,.85))
        self.assertEqual(result.targets[0],(game.ARENA.left+8,game.ARENA.top+8))
        self.assertEqual(result.targets[1],(game.ARENA.right-8,game.ARENA.bottom-8))
        result=self.frame(.05,hand(.05,.08,.12),hand(.05,.92,.83))
        self.assertGreater(result.targets[0][0],game.ARENA.left+8)
        self.assertLess(result.targets[0][0],game.ARENA.left+8+(.02/.41)*(game.ARENA.width-16))
        self.assertEqual(map_to_screen(-1,5,(.1,.1,.9,.9)),(0,1))

    def test_pinch_fires_once_per_pose_even_when_held_past_cooldown(self):
        self.arm()
        actions=[]
        for i in range(160):
            t=.25+i*.05
            actions.extend(self.frame(t,hand(t,.25,pinch=.1),hand(t,.75)).actions)
        self.assertEqual(actions,[(0,'dash')])
        for t in (8.3,8.4):self.frame(t,hand(t,.25),hand(t,.75))
        actions=[]
        for t in (8.5,8.6):actions.extend(self.frame(t,hand(t,.25,pinch=.1),hand(t,.75)).actions)
        self.assertEqual(actions,[(0,'dash')])

    def test_palm_and_v_fire_independently_once(self):
        self.arm()
        actions=[]
        for i in range(35):
            t=.25+i*.05
            actions.extend(self.frame(t,hand(t,.25,palm=True),hand(t,.75,victory=True)).actions)
        self.assertCountEqual(actions,[(0,'shield'),(1,'pulse')])

    def test_pinch_has_priority_over_other_gestures(self):
        self.arm()
        actions=[]
        for i in range(20):
            t=.25+i*.05
            actions.extend(self.frame(t,hand(t,.25,pinch=.1,palm=True,victory=True)).actions)
        self.assertEqual(actions,[(0,'dash')])

    def test_no_actions_on_startup_or_reacquisition_with_held_pose(self):
        for i in range(20):
            t=i*.05
            self.assertFalse(self.frame(t,hand(t,.25,pinch=.1)).actions)
        self.controls.reset()
        self.arm()
        self.frame(.25,hand(.25,.25,victory=True))
        self.frame(.3)
        actions=[]
        for i in range(20):
            t=.35+i*.05
            actions.extend(self.frame(t,hand(t,.25,victory=True)).actions)
        self.assertFalse(actions)

    def test_stale_frame_and_same_sequence_do_not_replay_actions(self):
        self.arm()
        self.tracker.samples.put(HandFrame(.25,(hand(.25,.25,pinch=.1),)))
        self.controls.poll(.25)
        self.tracker.samples.put(HandFrame(.35,(hand(.35,.25,pinch=.1),)))
        result=self.controls.poll(.35)
        self.assertEqual(result.actions,((0,'dash'),))
        self.assertFalse(self.controls.poll(.36).actions)
        result=self.controls.poll(.35+self.controls.camera.stale_after+.01)
        self.assertEqual(result.targets,(None,None))
        self.assertFalse(any(result.tracked))
        self.assertFalse(self.controls.gates[0].armed)

    def test_brief_p2_dropout_holds_status_and_filter_but_freezes_movement(self):
        self.arm()
        pointer_filter=self.controls.filters[1]
        previous=pointer_filter.pos
        result=self.frame(.25,hand(.25,.25))
        self.assertEqual(result.tracked,(True,True))
        self.assertEqual(result.held,(False,True))
        self.assertIsNone(result.targets[1])
        self.assertEqual(pointer_filter.pos,previous)
        self.assertFalse(result.actions)
        self.assertTrue(self.controls.gates[1].armed)
        result=self.frame(.3,hand(.3,.25),hand(.3,.76))
        self.assertEqual(result.held,(False,False))
        self.assertEqual(result.tracked,(True,True))
        self.assertIs(self.controls.filters[1],pointer_filter)
        self.assertIsNotNone(result.targets[1])

    def test_preview_renders_landmarks_and_can_be_hidden(self):
        self.tracker.preview_enabled=True
        preview=bytes([20,30,40])*(240*180)
        frame=HandFrame(0,(hand(0,.25),hand(0,.75)),preview,(240,180))
        self.controls.consume(frame,0)
        with patch.object(game.time,'monotonic',return_value=0):game.draw_hand_status(self.controls)
        rect=game.pygame.Rect(game.ARENA.right-252,game.ARENA.top+10,240,180)
        self.assertEqual(tuple(game.SCREEN.get_at((rect.left+10,rect.top+10)))[:3],(20,30,40))
        self.tracker.preview_enabled=False
        game.SCREEN.fill((4,5,6))
        game.draw_hand_status(self.controls)
        self.assertEqual(tuple(game.SCREEN.get_at((rect.left+10,rect.top+10)))[:3],(4,5,6))

    def test_p2_hold_expires_without_new_camera_frames(self):
        self.arm()
        self.tracker.samples.put(HandFrame(.25,(hand(.25,.25),)))
        self.controls.poll(.25)
        self.assertTrue(self.controls.held[1])
        self.controls.poll(.2+self.controls.camera.loss_grace+.01)
        self.assertFalse(self.controls.tracked[1])
        self.assertIsNone(self.controls.targets[1])

    def test_intro_gestures_are_not_queued_for_gameplay(self):
        for i in range(30):
            t=i*.05
            self.frame(t,hand(t,.25,pinch=.1),active=False)
        for i in range(20):
            t=1.5+i*.05
            self.assertFalse(self.frame(t,hand(t,.25,pinch=.1)).actions)

    def test_two_player_calibration_and_reset_preserve_regions(self):
        self.controls.start_calibration()
        self.arm()
        self.frame(.25,hand(.25,.1,.2,pinch=.1,wrist=(.25,.5)),hand(.25,.6,.2,pinch=.1,wrist=(.75,.5)))
        self.frame(.35,hand(.35,.1,.2,pinch=.1,wrist=(.25,.5)),hand(.35,.6,.2,pinch=.1,wrist=(.75,.5)))
        self.assertTrue(self.controls.calibrating)
        self.assertEqual(self.controls.calibration_points,[[(.1,.2)],[(.6,.2)]])
        # Move wrists in small steps so ownership continuity remains plausible.
        for i in range(1,7):
            t=.35+i*.05
            self.frame(t,hand(t,.1+.3*i/6,.2+.5*i/6,wrist=(.25,.5)),hand(t,.6+.3*i/6,.2+.5*i/6,wrist=(.75,.5)))
        self.frame(.7,hand(.7,.4,.7,pinch=.1,wrist=(.25,.5)),hand(.7,.9,.7,pinch=.1,wrist=(.75,.5)))
        result=self.frame(.8,hand(.8,.4,.7,pinch=.1,wrist=(.25,.5)),hand(.8,.9,.7,pinch=.1,wrist=(.75,.5)))
        self.assertFalse(self.controls.calibrating)
        self.assertEqual(self.controls.regions,[(.1,.2,.4,.7),(.6,.2,.9,.7)])
        self.assertFalse(result.actions)
        self.controls.reset(rebind=True)
        self.assertEqual(self.controls.regions,[(.1,.2,.4,.7),(.6,.2,.9,.7)])

    def test_missing_pointer_freezes_movement_and_ticks_cooldown(self):
        p=game.new_game()['players'][0]
        held={key:True for key in p.keys}
        pos=p.pos.copy()
        p.cooldowns['dash']=2
        p.update(.1,held,hand_mode=True)
        self.assertEqual(p.pos,pos)
        self.assertAlmostEqual(p.cooldowns['dash'],1.9)
        p.update(.1,held,pointer=(pos.x+2,pos.y+2),hand_mode=True)
        self.assertEqual(p.pos,pos)
        p.update(.1,held,pointer=(pos.x+100,pos.y),hand_mode=True)
        self.assertAlmostEqual(p.pos.x-pos.x,26)

    def test_game_loop_consumes_hand_skill_and_calibration_pauses_combat(self):
        state=game.new_game()
        camera=CameraConfig()
        controls=HandControls(self.tracker,game.ARENA,camera)
        timeline=[(0,1,False),(.05,1,False),(.15,1,False),(.2,1,False),(.25,.1,False),(.35,.1,False),(.4,.1,True),(.45,.1,True)]
        current=[0]
        frames=[0]
        before_calibration={}
        def events():
            frame_index=frames[0]
            frames[0]+=1
            if frame_index==len(timeline):
                self.assertEqual(state['elapsed'],before_calibration['elapsed'])
                self.assertEqual(state['boss_pos'],before_calibration['boss'])
                self.assertGreater(state['players'][0].cooldowns['dash'],0)
                return [game.pygame.event.Event(game.pygame.QUIT)]
            t,pinch,calibrating=timeline[frame_index]
            current[0]=t
            self.tracker.samples.put(HandFrame(t,(hand(t,.4,.7,pinch=pinch),hand(t,.8,.7))))
            if calibrating and not controls.calibrating:
                before_calibration['elapsed']=state['elapsed']
                before_calibration['boss']=state['boss_pos'].copy()
                # Capture current clock after the first frame enters calibration.
                return [game.pygame.event.Event(game.pygame.KEYDOWN,key=game.pygame.K_c)]
            return []
        with patch.object(game,'new_game',return_value=state),patch.object(game.time,'monotonic',side_effect=lambda:current[0]),patch.object(game.pygame.event,'get',side_effect=events),patch.object(game.pygame,'quit'):
            with self.assertRaises(SystemExit):game.reset_and_run(controls)

    def test_failed_calibration_cannot_replace_existing_region(self):
        self.controls.start_calibration()
        original=list(self.controls.regions)
        self.controls._calibrate(0,HandSample(0,True,.1,.2))
        self.controls._calibrate(0,HandSample(.1,True,.12,.21))
        self.assertFalse(self.controls.calibration_points[0])
        self.assertEqual(self.controls.regions,original)
        self.controls._calibrate(0,HandSample(.2,True,.1,.2))
        self.controls._calibrate(0,HandSample(.3,True,.4,.8))
        self.controls.reset()
        self.assertEqual(self.controls.regions,original)

    def test_camera_cleanup_on_inference_error(self):
        import numpy as np
        cap=SimpleNamespace(read=lambda:(True,np.zeros((10,10,3),dtype=np.uint8)),release=unittest.mock.Mock())
        tracker=HandTracker(CameraConfig())
        tracker._mp=SimpleNamespace(Image=lambda **kw:kw,ImageFormat=SimpleNamespace(SRGB=0))
        landmarker=SimpleNamespace(detect_for_video=unittest.mock.Mock(side_effect=RuntimeError('test inference failure')))
        with patch.object(tracker,'_open_camera',return_value=cap):
            with self.assertRaises(RuntimeError):tracker._loop(landmarker)
        cap.release.assert_called_once()

    def test_network_camera_uses_stream_backend_with_timeouts(self):
        import cv2
        camera=CameraConfig(source_url='http://192.168.1.50:4747/video')
        tracker=HandTracker(camera)
        cap=unittest.mock.Mock()
        cap.isOpened.return_value=True
        with patch.object(cv2,'VideoCapture',return_value=cap) as Capture:
            self.assertIs(tracker._open_camera(),cap)
            Capture.assert_called_once_with(camera.source_url,cv2.CAP_FFMPEG,
                [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,4000,cv2.CAP_PROP_READ_TIMEOUT_MSEC,1000])
        cap.isOpened.return_value=False
        with patch.object(cv2,'VideoCapture',return_value=cap):
            self.assertIsNone(tracker._open_camera())
        cap.release.assert_called_once()

    def test_main_accepts_camera_url(self):
        url='http://192.168.1.50:4747/video'
        with patch('hand_control.tracker.HandTracker') as Tracker,patch.object(game,'reset_and_run'),patch.object(game.pygame,'quit'):
            game.main(['--camera-url',url])
            self.assertEqual(Tracker.call_args.args[0].source_url,url)
            Tracker.return_value.stop.assert_called_once()

    def test_camera_pipeline_uses_whole_frame_and_publishes_two_hands(self):
        import numpy as np
        tracker=HandTracker(CameraConfig())
        tracker._mp=SimpleNamespace(Image=lambda **kw:kw,ImageFormat=SimpleNamespace(SRGB=0))
        cap=SimpleNamespace(read=lambda:(True,np.zeros((480,640,3),dtype=np.uint8)),release=unittest.mock.Mock())
        def detect(image,timestamp):
            self.assertEqual(image['data'].shape,(480,640,3))
            tracker._stop.set()
            category=[SimpleNamespace(category_name='Right',score=.99)]
            points=lambda x:[SimpleNamespace(x=x+i*.002,y=.7-i*.005,z=0) for i in range(21)]
            return SimpleNamespace(hand_landmarks=[points(.7),points(.2)],handedness=[category,category])
        detector=SimpleNamespace(detect_for_video=unittest.mock.Mock(side_effect=detect))
        with patch.object(tracker,'_open_camera',return_value=cap):tracker._loop(detector)
        detector.detect_for_video.assert_called_once()
        _,frame=tracker.samples.get()
        self.assertEqual(len(frame.hands),2)
        self.assertEqual(frame.preview_size,(240,180))
        self.assertEqual(len(frame.preview),240*180*3)
        controls=HandControls(tracker,game.ARENA)
        result=controls.consume(frame,frame.t)
        self.assertEqual(result.tracked,(True,True))
        self.assertLess(controls.raw[0].x,controls.raw[1].x)
        cap.release.assert_called_once()

    def test_main_keyboard_mode_and_camera_cleanup(self):
        with patch.object(game,'reset_and_run') as run,patch.object(game.pygame,'quit'):
            game.main(['--no-camera'])
            run.assert_called_once_with(None)
        with patch('hand_control.tracker.HandTracker') as Tracker,patch.object(game,'reset_and_run',side_effect=SystemExit),patch.object(game.pygame,'quit'):
            with self.assertRaises(SystemExit):game.main([])
            Tracker.return_value.start.assert_called_once()
            Tracker.return_value.stop.assert_called_once()


class LandmarkMeasurementTests(unittest.TestCase):
    def make_hand(self, scale=1, pinch_gap=1.2, fingers=(True,True,True,True)):
        import numpy as np
        points=np.zeros((21,3))
        def put(i,x,y):points[i,:2]=(.5+x*scale*.2,.8-y*scale*.2)
        put(0,0,0)
        for extended,(base,x) in zip(fingers,((5,-.35),(9,0),(13,.3),(17,.55))):
            put(base,x,1);put(base+1,x,1.45)
            put(base+2,x,1.75 if extended else 1.2)
            put(base+3,x,2 if extended else .95)
        put(3,-.9,.8)
        points[4,:2]=points[8,:2]-(pinch_gap*scale*.2,0)
        return points

    def test_index_tip_and_scale_invariant_pinch(self):
        points=self.make_hand(pinch_gap=.2)
        measured=measure_hand(points,1)
        self.assertEqual((measured.x,measured.y),tuple(points[8,:2]))
        near=measure_hand(self.make_hand(scale=1.6,pinch_gap=.2),1)
        far=measure_hand(self.make_hand(scale=.6,pinch_gap=.2),1)
        self.assertAlmostEqual(near.pinch,far.pinch)
        self.assertAlmostEqual(measured.pinch,.2)

    def test_palm_v_and_pinch_are_distinct(self):
        self.assertTrue(measure_hand(self.make_hand(),1).open_palm)
        self.assertTrue(measure_hand(self.make_hand(fingers=(True,True,False,False)),1).victory)
        pinch=measure_hand(self.make_hand(pinch_gap=.1),1)
        self.assertFalse(pinch.open_palm)
        self.assertFalse(pinch.victory)


if __name__=='__main__':unittest.main()
