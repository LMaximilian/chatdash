"""ChatDash v1.2 automated validation platforms.

Run:
    python3 -m unittest -v test_chatdash.py
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

import chatdash


class ChatDashTestBase(unittest.TestCase):
    _shared_game: chatdash.ChatDashGame | None = None

    @classmethod
    def setUpClass(cls) -> None:
        if ChatDashTestBase._shared_game is None:
            ChatDashTestBase._shared_game = chatdash.ChatDashGame(skip_onboarding=True)
        cls.game = ChatDashTestBase._shared_game
        cls.game.sound.muted = True


class DataValidationPlatform(ChatDashTestBase):
    def test_release_metadata_and_level_schema(self) -> None:
        self.assertEqual(chatdash.VERSION, "1.2.0")
        self.assertEqual(len(self.game.levels), 8)
        chatdash.sanity_check_levels(self.game.levels)
        for level in self.game.levels:
            self.assertEqual(sum(event.kind == "star" for event in level.events), 3)
            self.assertTrue(any(event.kind.startswith("chomper_") for event in level.events))
            self.assertEqual(level.events, sorted(level.events, key=lambda event: event.t))

    def test_every_portal_targets_a_real_mode(self) -> None:
        targets = {
            event.target
            for level in self.game.levels
            for event in level.events
            if event.kind == "portal"
        }
        self.assertTrue(targets <= chatdash.VALID_MODES)
        self.assertTrue({"cube", "ship", "ball", "wave", "robot", "spider", "swing"} <= targets)

    def test_level_eight_extreme_features_exist(self) -> None:
        kinds = {event.kind for event in self.game.levels[7].events}
        expected = {
            "quadruple", "needle_gate", "open_needle_gate", "laser_gate",
            "pendulum", "spinner", "crusher", "chomper_high", "chomper_low",
        }
        self.assertTrue(expected <= kinds)

    def test_score_never_requests_a_missing_pitch(self) -> None:
        calls: list[str] = []
        original_play = self.game.sound.play
        self.game.sound.play = calls.append
        try:
            for index, level in enumerate(self.game.levels):
                sequencer = chatdash.MusicSequencer(self.game.sound)
                for frame in range(int(chatdash.LEVEL_LENGTH * 60) + 1):
                    sequencer.update(frame / 60, level.bpm + index * 7, level.events, index)
        finally:
            self.game.sound.play = original_play
        requested = {
            name for name in calls
            if name.startswith("note_") or name.startswith("guitar_")
        }
        self.assertTrue(requested <= self.game.sound.sounds.keys())


class PhysicsPlatform(ChatDashTestBase):
    def test_all_player_modes_stay_in_bounds(self) -> None:
        player = chatdash.Player()
        for mode in sorted(chatdash.VALID_MODES):
            player.reset()
            player.set_mode(mode)
            for frame in range(600):
                if frame % 43 == 0:
                    player.action()
                player.update(1 / 120, held=(frame // 37) % 2 == 0)
                self.assertGreaterEqual(player.pos.y, 68)
                self.assertLessEqual(player.pos.y, chatdash.GROUND_Y)

    def test_every_obstacle_builds_and_renders(self) -> None:
        surface = pygame.Surface((chatdash.WIDTH, chatdash.HEIGHT), pygame.SRCALPHA)
        non_obstacles = {"portal", "star", "orb_yellow", "orb_blue"}
        obstacle_kinds = chatdash.VALID_EVENT_KINDS - non_obstacles
        for kind in sorted(obstacle_kinds):
            obstacle = chatdash.Obstacle(kind, 520, 400, chatdash.PINK)
            for _ in range(6):
                obstacle.update(1 / 60)
                obstacle.spike_polys()
                obstacle.draw(surface, obstacle.age)

    def test_laser_gate_has_ground_and_air_routes(self) -> None:
        level = self.game.levels[7]
        for mode, player_y in (("cube", 493), ("ship", 430), ("wave", 430), ("swing", 430)):
            player = chatdash.Player()
            player.set_mode(mode)
            player.pos.y = player_y
            laser = chatdash.Obstacle("laser_gate", chatdash.WIDTH + 60, level.speed, chatdash.RED)
            collisions = []
            for _ in range(240):
                laser.update(1 / 60)
                if mode != "cube":
                    player.pos.y = 430 + __import__("math").sin(laser.age * 2) * 30
                if abs(laser.x - player.pos.x) < 45:
                    collisions.append(laser.collides(player.rect()))
            self.assertTrue(collisions)
            self.assertFalse(any(collisions))

    def test_projectile_telegraph_precedes_damage(self) -> None:
        player = chatdash.Player()
        laser = chatdash.DeterrenceProjectile(
            "laser", chatdash.Vec2(500, player.pos.y), player.pos
        )
        laser.age = 0.1
        self.assertFalse(laser.collides(player.rect()))
        laser.age = 0.3
        self.assertTrue(laser.collides(player.rect()))

    def test_mode_transition_cannot_create_an_air_jump(self) -> None:
        player = chatdash.Player()
        player.set_mode("ship")
        player.pos.y = 220
        player.set_mode("cube")
        self.assertFalse(player.on_ground)
        self.assertFalse(player.action())


class UIStatePlatform(ChatDashTestBase):
    def test_reset_button_opens_from_every_page(self) -> None:
        game = self.game
        states = (
            chatdash.SIGN_IN, chatdash.INSTRUCTIONS, chatdash.PERSONALIZATION,
            chatdash.MENU, chatdash.LEVEL_SELECT, chatdash.PLAYING, chatdash.PAUSED,
            chatdash.CRASHED, chatdash.LEVEL_COMPLETE, chatdash.WIN,
        )
        for state in states:
            game.state = state
            game.reset_confirm_open = False
            game.handle_event(
                pygame.event.Event(
                    pygame.MOUSEBUTTONDOWN,
                    button=1,
                    pos=game.global_reset_rect().center,
                )
            )
            self.assertTrue(game.reset_confirm_open, state)
            _, cancel = game.reset_confirm_rects()
            game.handle_event(
                pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=cancel.center)
            )
            self.assertFalse(game.reset_confirm_open)

    def test_selector_launches_highlighted_level(self) -> None:
        game = self.game
        game.state = chatdash.MENU
        game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE))
        self.assertEqual(game.state, chatdash.LEVEL_SELECT)
        game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_6))
        game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
        self.assertEqual((game.state, game.level_index), (chatdash.PLAYING, 5))

    def test_death_summary_persists_and_back_navigates(self) -> None:
        game = self.game
        game.level_index = 4
        game.reset_level()
        game.level_time = 23.75
        game.attempt_obstacles_dodged = 9
        game.crash("TEST COLLISION")
        summary = game.death_summary
        self.assertEqual(game.state, chatdash.CRASHED)
        self.assertEqual(summary["cause"], "TEST COLLISION")
        for _ in range(180):
            game.update(1 / 60)
        self.assertIs(game.death_summary, summary)
        back = game.death_summary_back_rect()
        game.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=back.center)
        )
        self.assertEqual((game.state, game.selected_level), (chatdash.LEVEL_SELECT, 4))

    def test_security_system_is_reactive(self) -> None:
        game = self.game
        game.level_index = 7
        game.reset_level()
        game.security_alert = 34
        game.raise_security_alert(2)
        self.assertEqual(game.system_message, "MOVEMENT SIGNATURE CONFIRMED")
        game.security_reaction_cooldown = 0
        before = len(game.obstacles)
        game.raise_security_alert(35)
        self.assertGreater(len(game.obstacles), before)

    def test_render_every_major_state(self) -> None:
        game = self.game
        states = (
            chatdash.MENU, chatdash.LEVEL_SELECT, chatdash.PLAYING,
            chatdash.PAUSED, chatdash.CRASHED, chatdash.LEVEL_COMPLETE, chatdash.WIN,
        )
        for state in states:
            game.level_index = min(game.level_index, 7)
            if state == chatdash.CRASHED:
                game.reset_level()
                game.level_time = 5
                game.crash()
            else:
                game.state = state
            game.draw()


class OnboardingPlatform(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tempdir = tempfile.TemporaryDirectory()
        cls.profile_path = Path(cls.tempdir.name) / "profile.json"
        cls.game = chatdash.ChatDashGame(profile_path=cls.profile_path)
        cls.game.sound.muted = True

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tempdir.cleanup()

    def test_first_run_sign_in_tour_personalization_and_persistence(self) -> None:
        game = self.game
        self.assertEqual(game.state, chatdash.SIGN_IN)
        game.draw()
        for character in "Ada":
            game.handle_event(
                pygame.event.Event(
                    pygame.KEYDOWN, key=pygame.key.key_code(character.lower()), unicode=character
                )
            )
        game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_TAB, unicode=""))
        for character in "Lovelace":
            game.handle_event(
                pygame.event.Event(
                    pygame.KEYDOWN, key=pygame.key.key_code(character.lower()), unicode=character
                )
            )
        game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, unicode=""))
        self.assertEqual(game.state, chatdash.INSTRUCTIONS)

        for expected_page in range(4):
            self.assertEqual(game.instruction_page, expected_page)
            game.draw()
            game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RIGHT, unicode=""))
        self.assertEqual(game.state, chatdash.PERSONALIZATION)
        game.draw()

        game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RIGHT, unicode=""))
        game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_s, unicode="s"))
        game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_t, unicode="t"))
        game.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, unicode=""))
        self.assertEqual(game.state, chatdash.MENU)
        self.assertTrue(self.profile_path.exists())
        loaded = game.load_profile()
        self.assertEqual((loaded.first_name, loaded.last_name), ("Ada", "Lovelace"))
        self.assertEqual(loaded.color_name, "PINK")
        self.assertFalse(loaded.screen_shake)
        self.assertFalse(loaded.trails)

    def test_reset_button_cancels_or_deletes_everything(self) -> None:
        game = self.game
        game.level_deaths[3] = 7
        game.level_best_survival[3] = 44.0
        game.stars_collected = 9
        reset = game.global_reset_rect()
        game.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=reset.center)
        )
        self.assertTrue(game.reset_confirm_open)
        game.draw()
        _, cancel = game.reset_confirm_rects()
        game.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=cancel.center)
        )
        self.assertFalse(game.reset_confirm_open)
        self.assertTrue(self.profile_path.exists())

        game.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=reset.center)
        )
        confirm, _ = game.reset_confirm_rects()
        game.handle_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=confirm.center)
        )
        self.assertEqual(game.state, chatdash.SIGN_IN)
        self.assertFalse(self.profile_path.exists())
        self.assertEqual(game.name_fields, ["", ""])
        self.assertEqual(game.profile, chatdash.UserProfile())
        self.assertEqual(sum(game.level_deaths), 0)
        self.assertEqual(sum(game.level_best_survival), 0)
        self.assertEqual(game.stars_collected, 0)


class EndurancePlatform(ChatDashTestBase):
    def test_every_level_completes_at_multiple_frame_rates(self) -> None:
        game = self.game
        for fps in (30, 60, 120):
            dt = 1 / fps
            for level_index in range(len(game.levels)):
                game.level_index = level_index
                game.reset_level()
                for _ in range(int(62 * fps)):
                    game.player.invuln = 1.0
                    game.update(dt)
                    if game.state != chatdash.PLAYING:
                        break
                self.assertEqual(
                    game.state,
                    chatdash.LEVEL_COMPLETE,
                    f"level {level_index + 1} failed at {fps} FPS",
                )

    def test_level_one_collectible_route_at_multiple_frame_rates(self) -> None:
        game = self.game
        for fps in (30, 60, 120):
            game.level_index = 0
            game.reset_level()
            for _ in range(int(62 * fps)):
                game.player.invuln = 1.0
                ahead = [
                    obstacle for obstacle in game.obstacles
                    if obstacle.x >= game.player.pos.x - 15
                    and obstacle.kind not in ("ceiling", "air_low", "air_mid", "air_high")
                    and not obstacle.kind.startswith("chomper_")
                ]
                if game.player.on_ground and ahead:
                    nearest = min(ahead, key=lambda obstacle: obstacle.x)
                    if nearest.x - game.player.pos.x < 130:
                        game.handle_action()
                game.update(1 / fps)
                if game.state != chatdash.PLAYING:
                    break
            self.assertEqual(game.stars_collected, 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
