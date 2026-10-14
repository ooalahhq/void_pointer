import os
os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['SDL_AUDIODRIVER'] = 'dummy'

import unittest
from unittest.mock import patch
import pygame
import main as game


class BossGameplayTests(unittest.TestCase):
    def setUp(self):
        self.state = game.new_game()

    def test_stage_boundaries_and_patterns(self):
        self.assertEqual([game.boss_stage(hp) for hp in range(8, 0, -1)],
                         [1, 1, 1, 2, 2, 2, 3, 3])
        game.update_boss_attacks(self.state, 0)
        self.assertFalse(self.state['orbs'])
        game.update_boss_attacks(self.state, 1.2)
        self.assertEqual(len(self.state['orbs']), 1)
        self.state['boss_hp'] = 5
        game.update_boss_attacks(self.state, 2)
        self.assertFalse(self.state['orbs'])
        self.assertFalse(self.state['lasers'])
        game.update_boss_attacks(self.state, 3.3)
        self.assertEqual(len(self.state['orbs']), 3)
        game.update_boss_attacks(self.state, 4)
        self.assertEqual(len(self.state['lasers']), 1)

    def test_visual_effects_are_capped_expire_and_do_not_use_game_rng(self):
        fx=self.state['fx']
        rng_state=game.RNG.getstate()
        for _ in range(40):
            fx.burst((400,400),game.GOLD,40)
            fx.trail((420,400),game.CYAN)
        self.assertLessEqual(len(fx.particles),fx.MAX_PARTICLES)
        self.assertLessEqual(len(fx.rings),fx.MAX_RINGS)
        fx.draw(game.SCREEN)
        self.assertEqual(game.RNG.getstate(),rng_state)
        fx.update(1)
        self.assertFalse(fx.particles)
        self.assertFalse(fx.rings)

    def test_shake_is_bounded_decays_and_resets(self):
        fx=self.state['fx']
        fx.shake(100,.4)
        self.assertEqual(fx.shake_power,18)
        for _ in range(20):
            self.assertTrue(all(abs(value)<=18 for value in fx.offset()))
        fx.update(.2)
        for _ in range(20):
            self.assertTrue(all(abs(value)<=5 for value in fx.offset()))
        fx.update(.2)
        self.assertEqual(fx.offset(),(0,0))
        self.assertEqual(game.new_game()['fx'].offset(),(0,0))

    def test_effects_and_shake_leave_hud_unchanged(self):
        game.SCREEN.fill((21,32,43))
        marker=game.SCREEN.get_at((200,50))
        self.state['fx'].burst((200,95),game.GOLD,100,radius=100)
        self.state['fx'].shake(12)
        self.state['fx'].update(.1)
        clip=game.SCREEN.get_clip()
        game.draw_combat_fx(self.state)
        self.assertEqual(game.SCREEN.get_at((200,50)),marker)
        self.assertEqual(game.SCREEN.get_clip(),clip)

    def test_damage_feedback_only_when_damage_or_shield_block_occurs(self):
        p=self.state['players'][0]
        game.damage_player(self.state,p,False)
        self.assertEqual(p.hp,2)
        particles=len(self.state['fx'].particles)
        game.damage_player(self.state,p,False)
        self.assertEqual(len(self.state['fx'].particles),particles)
        p.invuln=0
        game.activate_skill(self.state,p,'shield')
        game.damage_player(self.state,p,True)
        self.assertTrue(p.alive)
        particles=len(self.state['fx'].particles)
        game.damage_player(self.state,p,True)
        self.assertEqual(len(self.state['fx'].particles),particles)

    def test_healing_spawn_interval_expiry_and_safe_position(self):
        due = self.state['next_healing']
        game.update_healing(self.state, due-.01)
        self.assertIsNone(self.state['healing'])
        game.update_healing(self.state, due)
        orb = self.state['healing']
        self.assertIsNotNone(orb)
        self.assertTrue(game.ARENA.collidepoint(orb.pos))
        self.assertGreaterEqual(orb.pos.distance_to(self.state['boss_pos']), 90)
        self.assertTrue(all(orb.pos.distance_to(p.pos)>=60 for p in self.state['players']))
        self.assertGreaterEqual(self.state['next_healing']-due, 10)
        self.assertLessEqual(self.state['next_healing']-due, 16)
        game.update_healing(self.state, due+1)
        self.assertIs(self.state['healing'], orb)
        game.update_healing(self.state, orb.expires)
        self.assertIsNone(self.state['healing'])

    def test_healing_full_hp_dead_players_and_single_consumer(self):
        p1,p2 = self.state['players']
        pos = p1.pos.copy()
        p2.pos = pos.copy()
        self.state['healing'] = game.HealingOrb(pos, 0)
        game.update_healing(self.state, 1)
        self.assertIsNotNone(self.state['healing'])
        p1.hp=0;p1.alive=False
        game.update_healing(self.state, 1)
        self.assertEqual(p1.hp, 0)
        self.assertIsNotNone(self.state['healing'])
        p2.hp=2
        game.update_healing(self.state, 1)
        self.assertEqual(p2.hp, 3)
        self.assertIsNone(self.state['healing'])
        self.assertEqual(len(self.state['effects']), 1)
        p1.alive=True;p1.hp=1;p2.hp=1
        self.state['healing'] = game.HealingOrb(pos, 0)
        game.update_healing(self.state, 1)
        self.assertEqual(p1.hp+p2.hp, 3)

    def test_healing_disabled_outside_boss_and_resets(self):
        for phase in ('intro','duel','end'):
            self.state['phase']=phase
            self.state['healing']=game.HealingOrb((400,400),0)
            self.state['next_healing']=0
            game.update_healing(self.state, 20)
            self.assertIsNone(self.state['healing'])
        fresh=game.new_game()
        self.assertIsNone(fresh['healing'])
        self.assertGreaterEqual(fresh['next_healing'],8)

    def test_skills_cooldowns_dash_direction_and_arena_bounds(self):
        p=self.state['players'][0]
        p.facing=pygame.Vector2(1,0)
        start=p.pos.copy()
        held={key:False for key in p.keys}
        self.assertTrue(game.activate_skill(self.state,p,'dash'))
        self.assertFalse(game.activate_skill(self.state,p,'dash'))
        p.update(.1,held)
        self.assertAlmostEqual(p.pos.x-start.x,85)
        p.hit(False)
        self.assertEqual(p.hp,3)
        p.pos.x=game.ARENA.right-9
        p.update(.05,held)
        self.assertEqual(p.pos.x,game.ARENA.right-8)
        p.update(4,held)
        self.assertTrue(game.activate_skill(self.state,p,'dash'))

    def test_shield_blocks_damage_then_expires(self):
        p=self.state['players'][0]
        self.assertTrue(game.activate_skill(self.state,p,'shield'))
        p.hit(True)
        self.assertTrue(p.alive)
        p.update(1.3,{key:False for key in p.keys})
        self.assertFalse(game.activate_skill(self.state,p,'shield'))
        p.hit(False)
        self.assertEqual(p.hp,2)

    def test_pulse_clears_nearby_orbs_and_keeps_lasers(self):
        p=self.state['players'][0]
        nearby=game.Orb(p.pos+pygame.Vector2(100,0),(0,0))
        far=game.Orb(p.pos+pygame.Vector2(151,0),(0,0))
        self.state['orbs']=[nearby,far]
        laser=game.Laser(True,p.pos.y,0)
        self.state['lasers']=[laser]
        self.assertTrue(game.activate_skill(self.state,p,'pulse'))
        self.assertEqual(self.state['orbs'],[far])
        self.assertEqual(self.state['lasers'],[laser])
        self.assertEqual(p.cooldowns['pulse'],12)
        self.assertEqual(len(self.state['effects']),1)

    def test_skills_reject_inactive_players_and_reset(self):
        p=self.state['players'][0]
        for phase in ('intro','end'):
            self.state['phase']=phase
            self.assertFalse(game.activate_skill(self.state,p,'dash'))
        self.state['phase']='boss'
        p.alive=False
        self.assertFalse(game.activate_skill(self.state,p,'shield'))
        p.alive=True
        self.assertFalse(game.activate_skill(self.state,p,'unknown'))
        self.assertTrue(all(value==0 for value in game.new_game()['players'][0].cooldowns.values()))

    def test_healing_and_skill_effects_render(self):
        orb=game.HealingOrb((400,400),0)
        for now in (0,1,6.5,7):orb.draw(now)
        for effect in (game.HealPulse((400,400)),game.PulseEffect((400,400),game.CYAN)):
            effect.draw()
            effect.update(.1)
            effect.draw()
            effect.update(1)
            self.assertEqual(effect.life,0)
        p=self.state['players'][0]
        game.activate_skill(self.state,p,'shield')
        game.activate_skill(self.state,p,'dash')
        p.draw()

    def test_last_stage_burst_has_warning_and_finite_timer(self):
        self.state['boss_hp'] = 2
        game.update_boss_attacks(self.state, 0)
        game.update_boss_attacks(self.state, 1.2)
        self.assertEqual(len(self.state['orbs']), 5)
        game.update_boss_attacks(self.state, 2.6)
        self.assertIsNotNone(self.state['ring_at'])
        self.assertEqual(len(self.state['orbs']), 5)
        game.update_boss_attacks(self.state, 3.39)
        self.assertEqual(len(self.state['orbs']), 5)
        game.update_boss_attacks(self.state, 3.41)
        self.assertEqual(len(self.state['orbs']), 17)
        self.assertIsNone(self.state['ring_at'])
        game.update_boss_attacks(self.state, 3.5)
        self.assertEqual(len(self.state['orbs']), 17)

    def test_boss_laser_warning_damage_invulnerability_and_expiry(self):
        p = self.state['players'][0]
        self.state['lasers'] = [game.Laser(True, p.pos.y, 0, 1.1, .45)]
        game.update_lasers(self.state, 1, .05, False)
        self.assertEqual(p.hp, 3)
        game.update_lasers(self.state, 1.2, .05, False)
        self.assertEqual(p.hp, 2)
        game.update_lasers(self.state, 1.3, .05, False)
        self.assertEqual(p.hp, 2)
        game.update_lasers(self.state, 1.6, .05, False)
        self.assertFalse(self.state['lasers'])

    def test_duel_laser_remains_lethal(self):
        p = self.state['players'][0]
        self.state['lasers'] = [game.Laser(True, p.pos.y, 0)]
        game.update_lasers(self.state, .9, .05, True)
        self.assertFalse(p.alive)

    def test_speed_changes_abruptly_and_movement_stays_in_arena(self):
        with patch.object(game, 'RNG', game.random.Random(42)):
            self.state['next_speed_change'] = 0
            game.update_boss_movement(self.state, 0, .05)
            self.assertTrue(self.state['boss_fast'])
            self.assertGreaterEqual(self.state['boss_speed'], 290)
            self.assertLessEqual(self.state['boss_speed'], 380)
            switch_at = self.state['next_speed_change']
            self.assertGreaterEqual(switch_at, .45)
            self.assertLessEqual(switch_at, .95)
            game.update_boss_movement(self.state, switch_at, .05)
            self.assertFalse(self.state['boss_fast'])
            self.assertGreaterEqual(self.state['boss_speed'], 65)
            self.assertLessEqual(self.state['boss_speed'], 110)
            self.assertGreaterEqual(self.state['next_speed_change']-switch_at, 1)
            self.assertLessEqual(self.state['next_speed_change']-switch_at, 2.2)
            for frame in range(1, 2001):
                game.update_boss_movement(self.state, switch_at+frame*.05, .05)
                pos = self.state['boss_pos']
                self.assertTrue(game.BOSS_BOUNDS.left <= pos.x <= game.BOSS_BOUNDS.right)
                self.assertTrue(game.BOSS_BOUNDS.top <= pos.y <= game.BOSS_BOUNDS.bottom)

    def test_movement_does_not_overshoot_and_stops_after_boss_phase(self):
        pos = self.state['boss_pos']
        target = pos + pygame.Vector2(1, 0)
        self.state['boss_target'] = target
        self.state['next_speed_change'] = 100
        game.update_boss_movement(self.state, 0, .05)
        self.assertEqual(pos, target)
        self.assertNotEqual(self.state['boss_target'], target)
        for phase in ('duel', 'end'):
            self.state['phase'] = phase
            game.update_boss_movement(self.state, 101, .05)
            self.assertEqual(pos, target)
        self.state['phase'] = 'boss'
        self.state['boss_hp'] = 0
        game.update_boss_movement(self.state, 101, .05)
        self.assertEqual(pos, target)
        fresh = game.new_game()
        self.assertEqual(fresh['boss_pos'], game.BOSS_START_POS)
        self.assertIsNot(fresh['boss_pos'], game.BOSS_START_POS)
        self.assertFalse(fresh['boss_fast'])

    def test_projectiles_follow_current_boss_position(self):
        self.state['boss_pos'] = pygame.Vector2(600, 330)
        game.update_boss_attacks(self.state, 1.2)
        self.assertEqual(self.state['orbs'][0].pos, pygame.Vector2(600, 370))
        self.state['boss_hp'] = 2
        game.update_boss_attacks(self.state, 2)
        self.state['ring_at'] = 2.5
        game.update_boss_attacks(self.state, 2.5)
        self.assertEqual(len(self.state['orbs']), 12)
        self.assertTrue(all(orb.pos == pygame.Vector2(600, 370) for orb in self.state['orbs']))

    def test_sword_strikes_moving_boss_at_current_position(self):
        state = self.state
        state['boss_pos'] = pygame.Vector2(650, 350)
        p = state['players'][0]
        p.pos = state['boss_pos'].copy()
        p.sword = True
        state['sword'] = None
        event_frames = [[], [pygame.event.Event(pygame.QUIT)]]
        with patch.object(game, 'new_game', return_value=state), patch.object(game, 'update_boss_movement'), patch.object(pygame.event, 'get', side_effect=event_frames), patch.object(pygame, 'quit'):
            with self.assertRaises(SystemExit):
                game.reset_and_run()
        self.assertEqual(state['boss_hp'], 7)
        self.assertEqual(state['hit_by'][0], 1)
        self.assertFalse(p.sword)
        self.assertEqual(len(state['effects']), 1)
        self.assertIsNotNone(state['sword'])

    def test_intro_finishes_automatically_or_can_be_skipped(self):
        for skip in (False, True):
            state = game.new_game(intro=True)
            start_pos = state['boss_pos'].copy()
            game.update_intro(state, 1)
            self.assertEqual(state['phase'], 'intro')
            self.assertEqual(state['elapsed'], 0)
            self.assertEqual(state['boss_pos'], start_pos)
            game.update_intro(state, game.INTRO_DURATION if not skip else 0, skip=skip)
            self.assertEqual(state['phase'], 'boss')
            self.assertEqual(state['elapsed'], 0)
            self.assertEqual(state['next_orb'], 1.2)

    def test_intro_loop_freezes_gameplay_until_space_or_enter(self):
        for key in (pygame.K_SPACE, pygame.K_RETURN):
            state = game.new_game(intro=True)
            frames = 0
            start_pos = state['boss_pos'].copy()
            def events():
                nonlocal frames
                frames += 1
                if frames == 4:
                    self.assertEqual(state['elapsed'], 0)
                    self.assertEqual(state['boss_pos'], start_pos)
                    self.assertFalse(state['orbs'])
                    return [pygame.event.Event(pygame.KEYDOWN, key=key)]
                if frames == 5:
                    self.assertEqual(state['phase'], 'boss')
                    self.assertFalse(state['orbs'])
                    return [pygame.event.Event(pygame.QUIT)]
                return []
            with patch.object(game, 'new_game', return_value=state), patch.object(pygame.event, 'get', side_effect=events), patch.object(pygame, 'quit'):
                with self.assertRaises(SystemExit):
                    game.reset_and_run()

    def test_intro_render_all_animation_stages(self):
        intro = game.TitleIntro((game.W, game.H))
        for t in (0, .5, 1.3, 1.8, 2.3, 3, 4.8, 5.5, game.INTRO_DURATION):
            intro.draw(game.SCREEN, t)
            self.assertEqual(game.SCREEN.get_clip(), game.SCREEN.get_rect())
        self.assertEqual(game.SCREEN.get_size(), (1280, 800))

    def test_dead_carrier_recovers_sword_once(self):
        p, survivor = self.state['players']
        p.hp = 1
        p.sword = True
        self.state['sword'] = None
        p.hit(False)
        self.assertFalse(p.sword)
        game.ensure_sword(self.state)
        sword = self.state['sword']
        self.assertIsNotNone(sword)
        self.assertTrue(game.ARENA.collidepoint(sword))
        self.assertGreater(sword.distance_to(survivor.pos), 60)
        self.assertGreater(sword.distance_to(self.state['boss_pos']), 75)
        game.ensure_sword(self.state)
        self.assertIs(self.state['sword'], sword)
        self.state['sword'] = None
        survivor.sword = True
        game.ensure_sword(self.state)
        self.assertIsNone(self.state['sword'])
        survivor.hit(True)
        game.ensure_sword(self.state)
        self.assertIsNone(self.state['sword'])

    def test_render_loop_all_phases_and_restart(self):
        state = self.state
        frames = 0
        def events():
            nonlocal frames
            frames += 1
            if frames == 2:
                state['boss_hp'] = 5
            elif frames == 3:
                state['boss_hp'] = 2
                state['effects'].append(game.Slash(state['players'][0].pos, state['boss_pos']))
            elif frames == 4:
                state['ring_at'] = state['elapsed'] + .8
            elif frames == 5:
                state['boss_hp'] = 0
            elif frames == 6:
                state['lasers'].append(game.Laser(True, 300, state['elapsed']))
            elif frames == 7:
                state['phase'] = 'end'
                state['message'] = 'DRAW'
            elif frames == 8:
                return [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_r)]
            elif frames == 9:
                return [pygame.event.Event(pygame.QUIT)]
            return []
        original_new_game = game.new_game
        with patch.object(game, 'new_game', side_effect=[state, original_new_game()]), patch.object(pygame.event, 'get', side_effect=events), patch.object(pygame, 'quit'):
            with self.assertRaises(SystemExit):
                game.reset_and_run()
        self.assertEqual(frames, 9)


if __name__ == '__main__':
    unittest.main()
