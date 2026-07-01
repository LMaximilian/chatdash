"""
ChatDash - a polished mini Geometry-Dash-style game.

Install:
    pip install pygame

Run:
    python chatdash.py

Controls:
    SPACE / UP / Left Mouse  = jump, flap, switch gravity, or fly
    P                         = pause
    R                         = restart current level after a crash
    M                         = mute / unmute sound
    ESC                       = quit
"""

from __future__ import annotations

from array import array
from functools import lru_cache
import json
import math
from pathlib import Path
import random
from dataclasses import dataclass
from typing import List, Tuple, Optional

import pygame

# -------------------------------
# Basic setup
# -------------------------------
WIDTH, HEIGHT = 1040, 620
FPS = 60
GROUND_Y = 515
PLAYER_X = 190
LEVEL_LENGTH = 60.0
VERSION = "1.2.0"
DEFAULT_PROFILE_PATH = Path(__file__).with_name("chatdash_profile.json")

Vec2 = pygame.math.Vector2
Color = Tuple[int, int, int]

WHITE = (245, 248, 255)
BLACK = (5, 7, 13)
PINK = (255, 70, 180)
CYAN = (68, 230, 255)
YELLOW = (255, 224, 90)
ORANGE = (255, 137, 62)
PURPLE = (169, 110, 255)
GREEN = (91, 255, 150)
RED = (255, 78, 92)
BLUE = (76, 136, 255)
DARK = (12, 14, 28)
PROFILE_COLORS = {"CYAN": CYAN, "PINK": PINK, "GREEN": GREEN, "YELLOW": YELLOW}

# Game states
MENU = "menu"
SIGN_IN = "sign_in"
INSTRUCTIONS = "instructions"
PERSONALIZATION = "personalization"
LEVEL_SELECT = "level_select"
PLAYING = "playing"
PAUSED = "paused"
CRASHED = "crashed"
LEVEL_COMPLETE = "level_complete"
WIN = "win"

VALID_MODES = {"cube", "ufo", "ship", "ball", "wave", "robot", "spider", "swing"}
VALID_EVENT_KINDS = {
    "portal", "star", "orb_yellow", "orb_blue",
    "single", "double", "triple", "quadruple", "ceiling", "block",
    "air_low", "air_mid", "air_high", "saw", "saw_mid", "moving_saw",
    "moving_block", "pendulum", "spinner", "rotating_cross", "crusher",
    "needle_gate", "open_needle_gate", "laser_gate", "chomper_high", "chomper_low",
}

INTRUDER_MESSAGES: Tuple[Tuple[Tuple[float, str], ...], ...] = (
    ((2, "UNAUTHORIZED CUBE DETECTED"), (31, "PLEASE LEAVE THE TEST TRACK")),
    ((2, "INTRUDER: TURN BACK NOW"), (30, "PORTAL ACCESS IS FORBIDDEN")),
    ((2, "YOU ARE IGNORING MY WARNINGS"), (29, "RETURN TO THE MENU. IMMEDIATELY.")),
    ((2, "SECURITY LEVEL INCREASED"), (28, "YOU WILL NOT REACH THE EXIT")),
    ((2, "FINAL POLITE WARNING EXPIRED"), (27, "STOP. MOVING. FORWARD.")),
    ((2, "INTRUDER REMOVAL ARMED"), (27, "I SAID STOP!"), (46, "LAST CHANCE TO RETREAT!")),
    ((1.5, "YOU SHOULD NOT BE HERE"), (24, "LETHAL DEFENSES AUTHORIZED"), (45, "TURN BACK!!!")),
    ((1, "INTRUDER LOCKED IN"), (15, "I AM GOING TO DELETE YOU..."),
     (34, "WHY ARE YOU STILL MOVING?!"), (50, "DELETE! DELETE! DELETE!")),
)


# -------------------------------
# Helpers
# -------------------------------
def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def pulse(t: float, speed: float = 1.0, lo: float = 0.0, hi: float = 1.0) -> float:
    s = (math.sin(t * speed) + 1) / 2
    return lerp(lo, hi, s)


def draw_glow_circle(surface: pygame.Surface, center: Tuple[int, int], radius: int, color: Color, layers: int = 4) -> None:
    # Draw transparent glow on a temporary surface.
    x, y = center
    for i in range(layers, 0, -1):
        alpha = int(30 * i)
        r = radius + i * 7
        glow = pygame.Surface((r * 2 + 4, r * 2 + 4), pygame.SRCALPHA)
        pygame.draw.circle(glow, (*color, alpha), (r + 2, r + 2), r)
        surface.blit(glow, (x - r - 2, y - r - 2), special_flags=pygame.BLEND_PREMULTIPLIED)
    pygame.draw.circle(surface, color, center, radius, 2)


def polygon_rect(points: List[Tuple[float, float]]) -> pygame.Rect:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return pygame.Rect(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


def rect_touches_poly_rough(rect: pygame.Rect, poly: List[Tuple[float, float]], shrink: int = 8) -> bool:
    # Fast, forgiving collision. This is intentionally not pixel-perfect.
    hit = polygon_rect(poly).inflate(-shrink, -shrink)
    return rect.colliderect(hit)


@lru_cache(maxsize=24)
def cached_font(name: str, size: int, bold: bool = False) -> pygame.font.Font:
    """Reuse fonts instead of rebuilding them inside draw loops."""
    return pygame.font.SysFont(name, size, bold=bold)


# -------------------------------
# Sound
# -------------------------------
class SoundManager:
    """Small synthesized sound bank; no external audio assets required."""

    def __init__(self) -> None:
        self.enabled = pygame.mixer.get_init() is not None
        self.muted = False
        self.sounds: dict[str, pygame.mixer.Sound] = {}
        if not self.enabled:
            return

        try:
            self.sounds = {
                "start": self.make_tone(440, 0.08, 0.35, end_frequency=760),
                "jump": self.make_tone(520, 0.07, 0.25, end_frequency=680),
                "flap": self.make_tone(760, 0.06, 0.22, end_frequency=480),
                "boost": self.make_tone(180, 0.055, 0.16, end_frequency=290, wave="triangle"),
                "gravity": self.make_tone(280, 0.10, 0.25, end_frequency=880, wave="triangle"),
                "teleport": self.make_tone(1100, 0.09, 0.25, end_frequency=250),
                "robot": self.make_tone(190, 0.12, 0.28, end_frequency=520, wave="triangle"),
                "warning": self.make_tone(210, 0.18, 0.22, end_frequency=160),
                "whoosh": self.make_noise(0.10, 0.12),
                "checkpoint": self.make_chord((440, 554, 659), 0.22, 0.25),
                "kick": self.make_tone(105, 0.10, 0.20, end_frequency=42),
                "hat": self.make_noise(0.035, 0.08),
                "bass": self.make_tone(110, 0.13, 0.12, end_frequency=108, wave="sine"),
                "music_note": self.make_tone(440, 0.10, 0.09, end_frequency=445, wave="sine"),
                "hazard_beat": self.make_chord((220, 440), 0.09, 0.16),
                "portal": self.make_tone(330, 0.20, 0.35, end_frequency=1050, wave="triangle"),
                "crash": self.make_noise(0.28, 0.42),
                "complete": self.make_chord((523, 659, 784), 0.42, 0.34),
                "win": self.make_chord((523, 659, 784, 1047), 0.75, 0.38),
                "pause": self.make_tone(300, 0.08, 0.22, end_frequency=220),
                "star": self.make_chord((880, 1109, 1319), 0.18, 0.22),
                "riser": self.make_tone(120, 0.65, 0.16, end_frequency=1400, wave="triangle"),
                "drama": self.make_chord((110, 165, 220, 330), 0.55, 0.16),
                "impact": self.make_chord((55, 110, 220), 0.32, 0.28),
                "snare": self.make_noise(0.11, 0.16),
                "select": self.make_tone(360, 0.07, 0.18, end_frequency=540, wave="triangle"),
                "chatdash_call": self.make_robot_chant(),
                "portal_slam": self.make_chord((82, 164, 329, 659), 0.30, 0.25),
                "spike_snap": self.make_tone(920, 0.065, 0.16, end_frequency=260),
                "saw_slice": self.make_noise(0.16, 0.20),
                "orb_burst": self.make_tone(420, 0.16, 0.20, end_frequency=1260, wave="sine"),
                "camera_sweep": self.make_tone(140, 0.38, 0.16, end_frequency=980, wave="sine"),
                "alarm": self.make_chord((196, 233), 0.23, 0.18),
                "drum_fill": self.make_noise(0.20, 0.18),
                "epic_chord_0": self.make_chord((110, 165, 220, 330, 440), 0.48, 0.16),
                "epic_chord_1": self.make_chord((130, 196, 261, 392, 523), 0.48, 0.16),
                "epic_chord_2": self.make_chord((146, 220, 293, 440, 587), 0.48, 0.16),
                "epic_chord_3": self.make_chord((164, 246, 329, 493, 659), 0.58, 0.18),
                "land": self.make_tone(95, 0.075, 0.16, end_frequency=58),
                "near_miss": self.make_noise(0.075, 0.10),
                "mode_warp": self.make_chord((196, 293, 440, 587), 0.22, 0.18),
                "machinery": self.make_tone(72, 0.18, 0.14, end_frequency=105, wave="sine"),
                "laser_charge": self.make_tone(310, 0.22, 0.14, end_frequency=1180, wave="sine"),
                "orb_near": self.make_tone(740, 0.08, 0.12, end_frequency=920, wave="sine"),
                "boundary": self.make_tone(180, 0.055, 0.10, end_frequency=130),
                "chomp": self.make_tone(115, 0.13, 0.20, end_frequency=58),
                "fire_spit": self.make_noise(0.18, 0.19),
                "laser_blast": self.make_tone(980, 0.20, 0.18, end_frequency=180, wave="sine"),
            }
            note_midis = {
                45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59,
                60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 74, 75, 77,
            }
            guitar_midis = {
                44, 46, 47, 49, 51, 52, 53, 54, 56, 58, 59, 60, 61, 63, 65,
            }
            for midi in sorted(note_midis):
                frequency = 440.0 * (2 ** ((midi - 69) / 12))
                self.sounds[f"note_{midi}"] = self.make_tone(frequency, 0.11, 0.10, wave="sine")
            for midi in sorted(guitar_midis):
                frequency = 440.0 * (2 ** ((midi - 69) / 12))
                self.sounds[f"guitar_{midi}"] = self.make_guitar_note(frequency, 0.13, 0.11)
            for name, root in (("a", 110.0), ("c", 130.81), ("g", 98.0), ("d", 146.83)):
                self.sounds[f"rock_chord_{name}"] = self.make_power_chord(root, 0.42, 0.15)
        except pygame.error:
            self.enabled = False
            self.sounds.clear()

    @staticmethod
    def envelope(i: int, total: int) -> float:
        attack = max(1, int(total * 0.06))
        release = max(1, int(total * 0.28))
        return min(1.0, i / attack, (total - i) / release)

    def make_tone(
        self,
        frequency: float,
        duration: float,
        volume: float,
        end_frequency: Optional[float] = None,
        wave: str = "square",
    ) -> pygame.mixer.Sound:
        sample_rate = pygame.mixer.get_init()[0]
        total = int(sample_rate * duration)
        phase = 0.0
        samples = array("h")
        for i in range(total):
            mix = i / max(1, total - 1)
            freq = lerp(frequency, end_frequency or frequency, mix)
            phase += math.tau * freq / sample_rate
            if wave == "triangle":
                raw = (2 / math.pi) * math.asin(math.sin(phase))
            elif wave == "sine":
                raw = math.sin(phase) * 0.82 + math.sin(phase * 2) * 0.18
            else:
                raw = 1.0 if math.sin(phase) >= 0 else -1.0
            samples.append(int(32767 * volume * self.envelope(i, total) * raw))
        return pygame.mixer.Sound(buffer=samples)

    def make_noise(self, duration: float, volume: float) -> pygame.mixer.Sound:
        sample_rate = pygame.mixer.get_init()[0]
        total = int(sample_rate * duration)
        samples = array("h")
        for i in range(total):
            decay = (1 - i / total) ** 2
            samples.append(int(32767 * volume * decay * random.uniform(-1, 1)))
        return pygame.mixer.Sound(buffer=samples)

    def make_chord(self, frequencies: Tuple[int, ...], duration: float, volume: float) -> pygame.mixer.Sound:
        sample_rate = pygame.mixer.get_init()[0]
        total = int(sample_rate * duration)
        samples = array("h")
        for i in range(total):
            t = i / sample_rate
            raw = sum(math.sin(math.tau * freq * t) for freq in frequencies) / len(frequencies)
            samples.append(int(32767 * volume * self.envelope(i, total) * raw))
        return pygame.mixer.Sound(buffer=samples)

    def make_robot_chant(self) -> pygame.mixer.Sound:
        """Synthesize an original robotic 'CHAT-DASH' call without voice assets."""
        sample_rate = pygame.mixer.get_init()[0]
        # duration, fundamental, first formant, second formant, noise amount
        segments = (
            (0.08, 120, 500, 1500, 0.85),   # "ch"
            (0.22, 155, 720, 1220, 0.06),   # "aa"
            (0.055, 115, 500, 1350, 0.75),  # "t"
            (0.07, 0, 0, 0, 0),             # dramatic gap
            (0.06, 125, 430, 1100, 0.30),   # "d"
            (0.25, 142, 700, 1180, 0.04),   # "aa"
            (0.17, 115, 600, 1700, 0.92),   # "sh"
        )
        samples = array("h")
        phase = 0.0
        for duration, fundamental, formant_a, formant_b, noise_amount in segments:
            total = max(1, int(sample_rate * duration))
            for i in range(total):
                if fundamental == 0:
                    samples.append(0)
                    continue
                phase += math.tau * fundamental / sample_rate
                t = i / sample_rate
                voiced = (
                    math.sin(phase) * 0.42
                    + math.sin(math.tau * formant_a * t) * 0.25
                    + math.sin(math.tau * formant_b * t) * 0.16
                )
                noise = random.uniform(-1, 1) * noise_amount
                edge = min(1.0, i / max(1, total * 0.08), (total - i) / max(1, total * 0.15))
                sample = clamp((voiced * (1 - noise_amount * 0.45) + noise * 0.55) * edge, -1, 1)
                samples.append(int(32767 * 0.34 * sample))

        # A short low echo gives the call its own chunky arcade identity.
        delay = int(sample_rate * 0.105)
        dry = list(samples)
        for i in range(delay, len(samples)):
            mixed = samples[i] + int(dry[i - delay] * 0.28)
            samples[i] = int(clamp(mixed, -32767, 32767))
        return pygame.mixer.Sound(buffer=samples)

    def make_guitar_note(self, frequency: float, duration: float, volume: float) -> pygame.mixer.Sound:
        sample_rate = pygame.mixer.get_init()[0]
        total = int(sample_rate * duration)
        samples = array("h")
        for i in range(total):
            t = i / sample_rate
            decay = (1 - i / total) ** 1.25
            raw = (
                math.sin(math.tau * frequency * t)
                + 0.38 * math.sin(math.tau * frequency * 2 * t)
                + 0.17 * math.sin(math.tau * frequency * 3 * t)
            )
            distorted = math.tanh(raw * 2.6)
            pick = random.uniform(-1, 1) * max(0, 1 - i / max(1, total * 0.06)) * 0.18
            samples.append(int(32767 * volume * decay * clamp(distorted + pick, -1, 1)))
        return pygame.mixer.Sound(buffer=samples)

    def make_power_chord(self, root: float, duration: float, volume: float) -> pygame.mixer.Sound:
        sample_rate = pygame.mixer.get_init()[0]
        total = int(sample_rate * duration)
        frequencies = (root, root * 1.5, root * 2.0)
        samples = array("h")
        for i in range(total):
            t = i / sample_rate
            decay = (1 - i / total) ** 0.72
            raw = sum(math.sin(math.tau * frequency * t) for frequency in frequencies) / 2.1
            distorted = math.tanh(raw * 2.9)
            samples.append(int(32767 * volume * decay * distorted))
        return pygame.mixer.Sound(buffer=samples)

    def play(self, name: str) -> None:
        if self.enabled and not self.muted and name in self.sounds:
            self.sounds[name].play()

    def toggle_mute(self) -> None:
        self.muted = not self.muted
        if self.muted and self.enabled:
            pygame.mixer.stop()


class MusicSequencer:
    """Tiny adaptive soundtrack locked to the level clock."""

    def __init__(self, sound: SoundManager) -> None:
        self.sound = sound
        self.last_step = -1
        self.last_section = -1
        self.call_played = False
        self.note_history: List[Tuple[int, float]] = []
        self.accented_events: set[int] = set()

    def reset(self) -> None:
        self.last_step = -1
        self.last_section = -1
        self.call_played = False
        self.note_history.clear()
        self.accented_events.clear()

    def update(self, level_time: float, bpm: float, events: List["Event"], level_index: int) -> None:
        # Eighth-note clock. The pattern grows denser every four bars.
        self.note_history = [(note, born) for note, born in self.note_history if level_time - born < 1.8]
        if level_index == 7 and level_time >= 15.05 and not self.call_played:
            self.call_played = True
            self.sound.play("chatdash_call")
        step_length = 60.0 / bpm / 2
        step = int(level_time / step_length)
        if step != self.last_step:
            self.last_step = step
            patterns = (
                (0, 3, 5, 7, 5, 3, 2, 3), (0, 2, 4, 7, 9, 7, 4, 2),
                (0, 5, 3, 10, 7, 3, 5, 2), (0, 1, 6, 5, 0, 8, 6, 3),
            )
            roots = (48, 50, 53, 45, 52, 47, 55, 44)
            section = int(level_time // 12)
            density = min(3, section)
            if section != self.last_section:
                if self.last_section >= 0:
                    self.sound.play("riser")
                    self.sound.play("impact")
                self.last_section = section
            if level_index == 7 and 14.65 <= level_time < 16.05:
                # Strip the arrangement back so the original synthetic title
                # call lands clearly before the Swing drop.
                for i, ev in enumerate(events):
                    if level_time >= ev.t:
                        self.accented_events.add(i)
                return
            if step % 4 == 0:
                self.sound.play("kick")
            elif step % 2 == 0 or density >= 2:
                self.sound.play("bass")
            else:
                self.sound.play("hat")
            if density >= 1 and step % 8 in (3, 7):
                self.sound.play("snare")
            if density >= 2 and step % 16 in (10, 11, 14, 15):
                self.sound.play("hat")
            if level_index == 7:
                # Straight rock pulse: eighth-note hats, kick on the drive,
                # snare on the backbeat, and an A-C-G-D power-chord loop.
                self.sound.play("hat")
                if step % 8 in (0, 4):
                    self.sound.play("kick")
                if step % 8 in (2, 6):
                    self.sound.play("snare")
                if step % 8 == 0:
                    chord = ("a", "c", "g", "d")[section % 4]
                    self.sound.play(f"rock_chord_{chord}")
            if level_index == 7 and step % 16 == 12:
                self.sound.play("drum_fill")
            if level_index == 7 and section >= 3 and step % 8 == 6:
                self.sound.play("alarm")
            slots = (0, 4) if density == 0 else ((0, 2, 4, 6) if density < 3 else (0, 1, 2, 4, 5, 6))
            if level_index == 7:
                slots = (0, 2, 4, 6) if section == 0 else (0, 1, 2, 3, 4, 5, 6, 7)
            if step % 8 in slots:
                melody = (0, 0, 3, 5, 0, 7, 5, 3) if level_index == 7 else patterns[level_index % len(patterns)]
                degree = melody[(step // 2 + section) % len(melody)]
                if level_index == 7:
                    octave = (0, 0, 2, 5, 7)[min(section, 4)]
                else:
                    octave = 12 if section % 2 else 0
                midi = roots[level_index % len(roots)] + degree + octave
                instrument = "guitar" if level_index == 7 else "note"
                self.sound.play(f"{instrument}_{midi}")
                self.note_history.append((midi, level_time))
                if level_index == 7 and section >= 1:
                    harmony = min(84, midi + 7)
                    self.sound.play(f"guitar_{harmony}")
                    self.note_history.append((harmony, level_time))
            if step % 16 == 0 and (level_index >= 4 or section >= 2):
                self.sound.play("drama")
            if level_index == 7 and step % 32 == 28:
                self.sound.play("riser")

        # Events are arrival times, so these musical accents occur exactly as
        # portals and hazards cross the player's vertical line.
        for i, ev in enumerate(events):
            if i not in self.accented_events and level_time >= ev.t:
                self.accented_events.add(i)
                self.sound.play("checkpoint" if ev.kind == "portal" or ev.kind.startswith("orb_") or ev.kind == "star" else "hazard_beat")
                if ev.kind == "portal":
                    self.sound.play("portal_slam")
                    if ev.target in ("swing", "wave"):
                        self.sound.play("camera_sweep")
                elif ev.kind.startswith("orb_"):
                    self.sound.play("orb_burst")
                elif "saw" in ev.kind or ev.kind in ("pendulum", "spinner", "rotating_cross"):
                    self.sound.play("saw_slice")
                elif ev.kind == "laser_gate":
                    self.sound.play("laser_charge")
                elif ev.kind.startswith("chomper_"):
                    self.sound.play("chomp")
                elif ev.kind.startswith("air"):
                    self.sound.play("whoosh")
                elif ev.kind in ("moving_block", "crusher", "needle_gate", "open_needle_gate"):
                    self.sound.play("machinery")
                elif ev.kind in ("single", "double", "triple", "quadruple", "ceiling", "block"):
                    self.sound.play("spike_snap")
                if level_index == 7 and ev.kind == "portal" and ev.target == "swing":
                    self.sound.play("impact")


# -------------------------------
# Level data
# -------------------------------
@dataclass
class Event:
    t: float
    kind: str
    lane: str = "ground"
    target: Optional[str] = None


@dataclass
class Level:
    name: str
    speed: float
    theme_a: Color
    theme_b: Color
    events: List[Event]
    bpm: float = 128


@dataclass
class UserProfile:
    first_name: str = ""
    last_name: str = ""
    color_name: str = "CYAN"
    screen_shake: bool = True
    trails: bool = True

    @property
    def complete(self) -> bool:
        return bool(self.first_name.strip() and self.last_name.strip())

    def to_dict(self) -> dict[str, object]:
        return {
            "first_name": self.first_name,
            "last_name": self.last_name,
            "color_name": self.color_name,
            "screen_shake": self.screen_shake,
            "trails": self.trails,
            "onboarding_complete": True,
            "version": VERSION,
        }


def add_spike_run(events: List[Event], start: float, end: float, every: float, choices: List[str], jitter: float = 0.0) -> None:
    t = start
    k = 0
    while t < end:
        kind = choices[k % len(choices)]
        jt = math.sin(k * 1.7) * jitter
        events.append(Event(round(t + jt, 2), kind))
        t += every
        k += 1


def add_burst(events: List[Event], start: float, pattern: List[Tuple[float, str, str]]) -> None:
    for dt, kind, lane in pattern:
        events.append(Event(round(start + dt, 2), kind, lane))


def build_levels() -> List[Level]:
    levels: List[Level] = []

    # Level 1: cube bootcamp. Clear rhythm, no portals.
    e: List[Event] = []
    e.append(Event(2.0, "portal", target="robot"))
    add_spike_run(e, 4, 18, 2.15, ["single", "single", "double"], jitter=0.05)
    e.append(Event(18.3, "portal", target="cube"))
    add_spike_run(e, 20, 38, 1.9, ["single", "double", "single", "single"], jitter=0.04)
    add_spike_run(e, 41, 57, 1.75, ["double", "single", "single"], jitter=0.03)
    levels.append(Level("1  CUBE COAST", 365, CYAN, BLUE, sorted(e, key=lambda x: x.t)))

    # Level 2: portals introduce UFO. Hazards remain gentle.
    e = []
    e.append(Event(2.0, "portal", target="ship"))
    add_spike_run(e, 4, 15, 1.85, ["single", "double", "single"])
    e.append(Event(16.0, "portal", target="ufo"))
    add_burst(e, 20, [
        (0.0, "air_low", "air"),
        (2.2, "air_mid", "air"),
        (4.5, "air_high", "air"),
        (6.8, "air_mid", "air"),
        (9.2, "air_low", "air"),
    ])
    e.append(Event(32.2, "portal", target="cube"))
    add_spike_run(e, 36, 58, 1.7, ["single", "single", "double", "single"], jitter=0.06)
    levels.append(Level("2  PORTAL POP", 405, PINK, PURPLE, sorted(e, key=lambda x: x.t)))

    # Level 3: more mode switching, faster, still rhythm-safe.
    e = []
    e.append(Event(1.8, "portal", target="wave"))
    add_spike_run(e, 3.8, 13, 1.65, ["single", "double", "single"])
    e.append(Event(14.5, "portal", target="ufo"))
    add_burst(e, 18, [
        (0.0, "air_mid", "air"),
        (1.9, "air_low", "air"),
        (4.1, "air_high", "air"),
        (6.3, "air_mid", "air"),
        (8.6, "air_low", "air"),
    ])
    e.append(Event(30.5, "portal", target="ball"))
    add_spike_run(e, 34, 47, 1.55, ["single", "double", "single", "double"])
    e.append(Event(48.5, "portal", target="ship"))
    add_burst(e, 52, [
        (0.0, "air_low", "air"),
        (2.0, "air_mid", "air"),
        (4.2, "air_high", "air"),
    ])
    levels.append(Level("3  SHARP SKY", 445, GREEN, CYAN, sorted(e, key=lambda x: x.t)))

    # Level 4: denser and more dramatic. Keeps large gaps around portal transitions.
    e = []
    e.append(Event(1.8, "portal", target="spider"))
    add_spike_run(e, 3.5, 17, 1.48, ["single", "double", "single", "single"])
    e.append(Event(18.8, "portal", target="ufo"))
    add_burst(e, 22, [
        (0.0, "air_low", "air"),
        (1.75, "air_mid", "air"),
        (3.65, "air_high", "air"),
        (5.6, "air_mid", "air"),
        (7.7, "air_low", "air"),
        (10.0, "air_high", "air"),
    ])
    e.append(Event(36.0, "portal", target="cube"))
    add_spike_run(e, 39.2, 57.8, 1.42, ["double", "single", "single", "double"], jitter=0.03)
    levels.append(Level("4  NEON TEETH", 485, ORANGE, PINK, sorted(e, key=lambda x: x.t)))

    # Level 5: final sprint. Faster, but no impossible triple walls.
    e = []
    e.append(Event(1.5, "portal", target="robot"))
    add_spike_run(e, 3.2, 14, 1.35, ["single", "double", "single"])
    e.append(Event(15.8, "portal", target="ufo"))
    add_burst(e, 19.2, [
        (0.0, "air_mid", "air"),
        (1.55, "air_low", "air"),
        (3.25, "air_high", "air"),
        (5.1, "air_mid", "air"),
        (7.05, "air_low", "air"),
        (9.2, "air_high", "air"),
    ])
    e.append(Event(31.5, "portal", target="cube"))
    add_spike_run(e, 34.6, 45.6, 1.32, ["single", "double", "single", "single"], jitter=0.02)
    e.append(Event(47.4, "portal", target="ufo"))
    add_burst(e, 51.0, [
        (0.0, "air_low", "air"),
        (1.6, "air_mid", "air"),
        (3.25, "air_high", "air"),
        (5.1, "air_mid", "air"),
    ])
    levels.append(Level("5  UFO FINALE", 520, YELLOW, ORANGE, sorted(e, key=lambda x: x.t)))

    # Level 6: every new form gets a readable showcase before the finale.
    e = [Event(5.0, "portal", target="ship")]
    add_burst(e, 9, [(0, "air_low", "air"), (2.0, "air_high", "air"), (4.0, "air_mid", "air")])
    e += [Event(17.0, "portal", target="ball")]
    add_spike_run(e, 20.5, 28, 1.65, ["single", "ceiling", "double"])
    e += [Event(30.0, "portal", target="robot")]
    add_spike_run(e, 33.5, 42, 1.48, ["block", "single", "saw"])
    e += [Event(44.0, "portal", target="spider")]
    add_spike_run(e, 47.5, 58, 1.42, ["single", "ceiling", "saw"])
    levels.append(Level("6  FORM FACTORY", 500, GREEN, PURPLE, sorted(e, key=lambda x: x.t)))

    # Level 7: wave corridors and rapid final-form switching.
    e = [Event(3.5, "portal", target="wave")]
    add_burst(e, 7, [
        (0, "air_low", "air"), (1.4, "air_high", "air"), (2.8, "air_low", "air"),
        (4.2, "air_high", "air"), (5.6, "air_mid", "air"), (7.0, "air_low", "air"),
    ])
    e += [Event(16.0, "portal", target="ship")]
    add_burst(e, 19.5, [(0, "saw_mid", "air"), (1.5, "air_high", "air"), (3, "air_low", "air"), (4.5, "saw_mid", "air")])
    e += [Event(26.0, "portal", target="ball")]
    add_spike_run(e, 29.5, 38, 1.35, ["ceiling", "double", "saw"])
    e += [Event(40.0, "portal", target="spider")]
    add_spike_run(e, 43.2, 50, 1.28, ["single", "ceiling", "saw"])
    e += [Event(51.5, "portal", target="robot")]
    add_spike_run(e, 54.8, 59, 1.25, ["block", "double", "saw"])
    e += [Event(10.0, "orb_yellow"), Event(23.0, "orb_blue"), Event(47.0, "orb_yellow")]
    levels.append(Level("7  HYPERDRIVE", 550, YELLOW, RED, sorted(e, key=lambda x: x.t)))

    # Level 8: an original tribute to Dash's 2.2-style pacing—very short form
    # sections, swing gravity, camera theatrics, interactive orbs, and a finale
    # that cycles through nearly the entire roster.
    e = [
        Event(2.0, "portal", target="spider"), Event(3.7, "single"),
        Event(5.2, "portal", target="cube"), Event(6.8, "double"),
        Event(7.5, "orb_yellow"), Event(8.3, "portal", target="spider"),
        Event(9.9, "ceiling"), Event(11.4, "portal", target="ball"),
        Event(13.2, "single"), Event(14.5, "ceiling"),
        Event(16.1, "portal", target="swing"), Event(17.8, "needle_gate"),
        Event(18.65, "pendulum"), Event(19.5, "rotating_cross"), Event(20.4, "laser_gate"),
        Event(22.0, "portal", target="cube"), Event(23.7, "triple"),
        Event(25.3, "portal", target="robot"), Event(27.0, "moving_block"),
        Event(28.6, "portal", target="ball"), Event(30.3, "open_needle_gate"),
        Event(31.0, "orb_blue"), Event(31.15, "spinner"), Event(32.0, "laser_gate"),
        Event(32.9, "chomper_high"),
        Event(34.5, "portal", target="swing"), Event(36.2, "needle_gate"),
        Event(37.05, "pendulum"), Event(37.9, "rotating_cross"), Event(38.8, "laser_gate"),
        Event(40.4, "portal", target="spider"), Event(42.0, "single"),
        Event(43.6, "portal", target="cube"), Event(45.3, "quadruple"),
        Event(46.0, "orb_yellow"), Event(46.15, "moving_block"),
        Event(47.0, "laser_gate"), Event(48.0, "triple"),
        Event(49.6, "portal", target="ship"), Event(51.3, "needle_gate"),
        Event(52.15, "air_low"), Event(53.0, "chomper_low"), Event(53.9, "crusher"),
        Event(55.5, "portal", target="robot"), Event(57.2, "saw"),
        Event(58.8, "portal", target="wave"),
    ]
    levels.append(Level("8  DASH REACTOR", 590, RED, YELLOW, sorted(e, key=lambda x: x.t), bpm=176))

    # Put one unmistakable authored chomper encounter in every level. Each
    # replaces an existing hazard at the same timestamp, so the rhythm and
    # portal safety windows remain intact.
    chomper_deployments = (10.40, 11.40, 10.40, 10.90, 9.95, 13.00, 12.60, 3.70)
    for level, deployment_time in zip(levels, chomper_deployments):
        candidates = [
            event for event in level.events
            if event.kind != "portal" and not event.kind.startswith("orb_")
        ]
        replaced = min(candidates, key=lambda event: abs(event.t - deployment_time))
        replaced.kind = "chomper_high"

    # Hand-checked collectible windows. Grounded forms receive low stars in
    # recovery gaps; flying forms receive mid-lane stars with generous space.
    star_layouts = (
        ((11.50, "low"), (26.65, "low"), (39.50, "low")),
        ((14.60, "mid"), (34.10, "low"), (48.75, "low")),
        ((13.25, "mid"), (28.55, "mid"), (50.25, "mid")),
        ((17.80, "low"), (34.00, "mid"), (58.70, "low")),
        ((14.90, "low"), (29.95, "mid"), (49.20, "mid")),
        ((7.00, "mid"), (31.75, "low"), (45.75, "low")),
        ((6.00, "mid"), (27.75, "low"), (53.15, "low")),
        ((2.80, "low"), (24.60, "low"), (54.80, "mid")),
    )
    for level, layout in zip(levels, star_layouts):
        for t, lane in layout:
            level.events.append(Event(t, "star", lane=lane))
        level.events.sort(key=lambda event: event.t)
    return levels


def sanity_check_levels(levels: List[Level]) -> None:
    """Catch unfair obvious layout problems.

    This is not a perfect AI solver, but it prevents the design mistakes that
    usually make dash games impossible: hazards spaced too tightly, portals
    embedded inside hazards, or late hazards after the level should be over.
    """
    for idx, level in enumerate(levels, 1):
        if level.speed <= 0 or level.bpm <= 0:
            raise ValueError(f"Level {idx}: speed and BPM must be positive")
        if level.events != sorted(level.events, key=lambda event: event.t):
            raise ValueError(f"Level {idx}: events are not sorted")
        if any(event.t < 0 for event in level.events):
            raise ValueError(f"Level {idx}: negative event timestamp")
        for event in level.events:
            if event.kind not in VALID_EVENT_KINDS:
                raise ValueError(f"Level {idx}: unknown event kind {event.kind!r}")
            if event.kind == "portal" and event.target not in VALID_MODES:
                raise ValueError(f"Level {idx}: invalid portal target {event.target!r}")
        if not any(event.kind.startswith("chomper_") for event in level.events):
            raise ValueError(f"Level {idx}: deterrence chomper is missing")
        dangers = [ev for ev in level.events if ev.kind not in ("star", "portal") and not ev.kind.startswith("orb_")]
        stars = [ev for ev in level.events if ev.kind == "star"]
        if len(stars) != 3:
            raise ValueError(f"Level {idx}: expected exactly three stars, found {len(stars)}")
        for star in stars:
            clearance = min(abs(star.t - ev.t) for ev in dangers)
            if clearance + 1e-6 < 0.85:
                raise ValueError(f"Level {idx}: star lacks a safe timing window ({clearance:.2f}s): {star}")
            if star.lane not in ("low", "mid"):
                raise ValueError(f"Level {idx}: unreachable star lane: {star}")
        last_hazard_t = -999.0
        last_portal_t = -999.0
        for ev in level.events:
            if ev.t >= LEVEL_LENGTH - 0.6:
                raise ValueError(f"Level {idx}: event too close to the 60s finish: {ev}")
            if ev.kind == "portal":
                if ev.t - last_hazard_t + 1e-6 < 1.15:
                    raise ValueError(f"Level {idx}: portal too soon after hazard: {ev}")
                last_portal_t = ev.t
                continue
            if ev.kind.startswith("orb_") or ev.kind == "star":
                continue

            # Hazards must not arrive too rapidly. Faster levels still need a fair rhythm.
            min_gap = 0.80 if idx == 8 else (1.20 if level.speed < 480 else 1.15)
            if ev.t - last_hazard_t + 1e-6 < min_gap:
                raise ValueError(f"Level {idx}: hazards too close: {last_hazard_t:.2f} -> {ev.t:.2f}")
            if ev.t - last_portal_t + 1e-6 < 1.60:
                raise ValueError(f"Level {idx}: hazard too soon after portal: {ev}")
            last_hazard_t = ev.t


# -------------------------------
# Objects
# -------------------------------
class Particle:
    def __init__(self, pos: Vec2, vel: Vec2, color: Color, life: float, radius: float):
        self.pos = Vec2(pos)
        self.vel = Vec2(vel)
        self.color = color
        self.life = life
        self.max_life = life
        self.radius = radius

    def update(self, dt: float) -> bool:
        self.life -= dt
        self.pos += self.vel * dt
        self.vel *= 0.985
        self.vel.y += 180 * dt
        return self.life > 0

    def draw(self, surf: pygame.Surface) -> None:
        if self.life <= 0:
            return
        a = int(255 * (self.life / self.max_life))
        r = max(1, int(self.radius * (self.life / self.max_life)))
        pygame.draw.circle(surf, (*self.color, a), (int(self.pos.x), int(self.pos.y)), r)


class Trail:
    def __init__(self):
        self.points: List[Vec2] = []
        self.max_points = 28
        self._tick = 0

    def clear(self) -> None:
        self.points.clear()

    def update(self, attach_pos: Vec2, dt: float) -> None:
        self._tick += 1
        # Add points frequently so turns are crisp and angular.
        if not self.points or self.points[-1].distance_to(attach_pos) > 8 or self._tick % 2 == 0:
            self.points.append(Vec2(attach_pos))
        while len(self.points) > self.max_points:
            self.points.pop(0)

    def draw(self, surf: pygame.Surface, color_a: Color, color_b: Color, time_s: float) -> None:
        if len(self.points) < 2:
            return

        # Make a deliberately sharp zig-zag streamer attached to the middle.
        sharp_points: List[Tuple[int, int]] = []
        pts = self.points[-self.max_points:]
        for i, p in enumerate(pts):
            age = i / max(1, len(pts) - 1)
            # alternating perpendicular kink creates sharp turns in the streamer.
            if 0 < i < len(pts) - 1:
                prev_p = pts[i - 1]
                next_p = pts[i + 1]
                tangent = next_p - prev_p
                if tangent.length_squared() > 0:
                    perp = Vec2(-tangent.y, tangent.x).normalize()
                else:
                    perp = Vec2(0, 1)
                amp = (1 - age) * 18 + 3
                sign = -1 if i % 2 else 1
                p = p + perp * amp * sign
            sharp_points.append((int(p.x), int(p.y)))

        # Limit the alpha buffer to the trail's local bounds instead of
        # allocating a full-screen surface every frame.
        bounds = polygon_rect(sharp_points).inflate(46, 46)
        bounds = bounds.clip(pygame.Rect(0, 0, WIDTH, HEIGHT))
        local_points = [(x - bounds.x, y - bounds.y) for x, y in sharp_points]
        glow = pygame.Surface((max(1, bounds.w), max(1, bounds.h)), pygame.SRCALPHA)
        for width, alpha in [(10, 30), (7, 45), (4, 90)]:
            pygame.draw.lines(glow, (*color_a, alpha), False, local_points, width)
        surf.blit(glow, bounds.topleft, special_flags=pygame.BLEND_PREMULTIPLIED)

        # Main segmented line, color-shifted.
        for i in range(len(sharp_points) - 1):
            mix = i / max(1, len(sharp_points) - 2)
            c = tuple(int(lerp(color_a[j], color_b[j], mix)) for j in range(3))
            width = max(2, int(7 * mix + 1))
            pygame.draw.line(surf, c, sharp_points[i], sharp_points[i + 1], width)

        # tiny sharp shards on turns
        for i in range(2, len(sharp_points) - 2, 5):
            p = Vec2(sharp_points[i])
            size = 6 + int(4 * pulse(time_s + i, 5))
            tri = [(p.x, p.y - size), (p.x - size * 0.55, p.y + size * 0.7), (p.x + size * 0.55, p.y + size * 0.7)]
            pygame.draw.polygon(surf, color_b, tri)


class Player:
    def __init__(self):
        self.mode = "cube"
        self.size = 44
        self.pos = Vec2(PLAYER_X, GROUND_Y - self.size / 2)
        self.vel = Vec2(0, 0)
        self.on_ground = True
        self.rotation = 0.0
        self.trail = Trail()
        self.invuln = 0.0
        self.gravity_dir = 1
        self.thrusting = False
        self.just_landed = False
        self.hit_boundary = False
        self.trail_visible = True

    def reset(self) -> None:
        self.mode = "cube"
        self.pos = Vec2(PLAYER_X, GROUND_Y - self.size / 2)
        self.vel = Vec2(0, 0)
        self.on_ground = True
        self.rotation = 0.0
        self.trail.clear()
        self.invuln = 0.0
        self.gravity_dir = 1
        self.thrusting = False
        self.just_landed = False
        self.hit_boundary = False
        self.trail_visible = True

    def set_mode(self, mode: str) -> None:
        if mode not in VALID_MODES:
            raise ValueError(f"Unknown player mode: {mode}")
        self.mode = mode
        self.gravity_dir = 1
        self.vel.y = -240 if mode in ("ufo", "ship") else 0
        self.pos.y = clamp(self.pos.y, 80, GROUND_Y - self.size / 2)
        floor_y = GROUND_Y - self.size / 2
        self.on_ground = mode in ("cube", "robot") and self.pos.y >= floor_y - 1
        self.trail.clear()

    def rect(self) -> pygame.Rect:
        s = self.size
        if self.mode in ("ufo", "ship", "wave", "swing"):
            s = 42
        return pygame.Rect(int(self.pos.x - s / 2), int(self.pos.y - s / 2), s, s).inflate(-8, -8)

    def action(self) -> bool:
        if self.mode in ("cube", "robot"):
            if self.on_ground:
                self.vel.y = -980 if self.mode == "robot" else -790
                self.on_ground = False
                return True
        elif self.mode == "ufo":
            # UFO tap-flap. Strong but controlled.
            self.vel.y = -520
            self.on_ground = False
            return True
        elif self.mode == "ball":
            self.gravity_dir *= -1
            self.vel.y = 430 * self.gravity_dir
            return True
        elif self.mode == "swing":
            self.gravity_dir *= -1
            self.vel.y = 360 * self.gravity_dir
            return True
        elif self.mode == "spider":
            self.gravity_dir *= -1
            self.pos.y = 82 if self.gravity_dir < 0 else GROUND_Y - self.size / 2
            self.vel.y = 0
            return True
        return False

    def update(self, dt: float, held: bool = False) -> None:
        self.invuln = max(0.0, self.invuln - dt)
        self.just_landed = False
        self.hit_boundary = False
        self.thrusting = held and self.mode in ("ship", "wave")
        if self.mode in ("cube", "robot"):
            was_grounded = self.on_ground
            self.vel.y += 2300 * dt
            self.pos.y += self.vel.y * dt
            floor_y = GROUND_Y - self.size / 2
            if self.pos.y >= floor_y:
                self.pos.y = floor_y
                self.vel.y = 0
                self.on_ground = True
                self.just_landed = not was_grounded
                # Snap rotation to square-ish angles for polish.
                self.rotation = round(self.rotation / 90) * 90
            else:
                self.on_ground = False
                self.rotation += (600 if self.mode == "robot" else 430) * dt
        elif self.mode == "ufo":
            self.vel.y += 1450 * dt
            self.vel.y = clamp(self.vel.y, -650, 650)
            self.pos.y += self.vel.y * dt
            # Keep UFO inside screen. Touching floor/ceiling is allowed but bouncy.
            top = 72
            bottom = GROUND_Y - 42
            if self.pos.y < top:
                self.pos.y = top
                self.vel.y = 90
                self.hit_boundary = True
            if self.pos.y > bottom:
                self.pos.y = bottom
                self.vel.y = -80
                self.hit_boundary = True
            self.rotation = clamp(self.vel.y * 0.08, -35, 35)
        elif self.mode == "ship":
            self.vel.y += (-1250 if held else 900) * dt
            self.vel.y = clamp(self.vel.y, -440, 440)
            self.pos.y += self.vel.y * dt
            self.hit_boundary = self.pos.y < 72 or self.pos.y > GROUND_Y - 38
            self.pos.y = clamp(self.pos.y, 72, GROUND_Y - 38)
            self.rotation = clamp(self.vel.y * 0.07, -28, 28)
        elif self.mode == "wave":
            self.vel.y = -390 if held else 390
            self.pos.y += self.vel.y * dt
            self.hit_boundary = self.pos.y < 68 or self.pos.y > GROUND_Y - 34
            self.pos.y = clamp(self.pos.y, 68, GROUND_Y - 34)
            self.rotation = -45 if held else 45
        elif self.mode == "swing":
            self.vel.y += 1050 * self.gravity_dir * dt
            self.vel.y = clamp(self.vel.y, -470, 470)
            self.pos.y += self.vel.y * dt
            self.hit_boundary = self.pos.y < 72 or self.pos.y > GROUND_Y - 38
            self.pos.y = clamp(self.pos.y, 72, GROUND_Y - 38)
            self.rotation = clamp(self.vel.y * 0.075, -32, 32)
        elif self.mode in ("ball", "spider"):
            if self.mode == "ball":
                self.vel.y += 1850 * self.gravity_dir * dt
                self.pos.y += self.vel.y * dt
            top, bottom = 76, GROUND_Y - self.size / 2
            if self.pos.y >= bottom:
                self.hit_boundary = self.vel.y > 0
                self.pos.y, self.vel.y = bottom, min(0, self.vel.y)
            if self.pos.y <= top:
                self.hit_boundary = self.vel.y < 0
                self.pos.y, self.vel.y = top, max(0, self.vel.y)
            self.rotation += 500 * self.gravity_dir * dt

        self.trail.update(Vec2(self.pos.x, self.pos.y), dt)

    def draw_cube(self, surf: pygame.Surface, color_a: Color, color_b: Color) -> None:
        s = self.size
        points = [Vec2(-s / 2, -s / 2), Vec2(s / 2, -s / 2), Vec2(s / 2, s / 2), Vec2(-s / 2, s / 2)]
        rad = math.radians(self.rotation)
        rot = []
        for p in points:
            q = Vec2(p.x * math.cos(rad) - p.y * math.sin(rad), p.x * math.sin(rad) + p.y * math.cos(rad))
            rot.append((self.pos.x + q.x, self.pos.y + q.y))

        # Shadow
        shadow_w = int(55 * (1 - clamp((GROUND_Y - self.pos.y) / 260, 0, 0.7)))
        pygame.draw.ellipse(surf, (0, 0, 0, 80), (PLAYER_X - shadow_w // 2, GROUND_Y + 12, shadow_w, 10))

        # Glow and body
        pygame.draw.polygon(surf, color_b, rot)
        inner = []
        for x, y in rot:
            inner.append((lerp(x, self.pos.x, 0.18), lerp(y, self.pos.y, 0.18)))
        pygame.draw.polygon(surf, color_a, inner)
        pygame.draw.polygon(surf, WHITE, rot, 3)

        # Face mark / middle attachment dot.
        pygame.draw.circle(surf, BLACK, (int(self.pos.x), int(self.pos.y)), 5)
        pygame.draw.circle(surf, WHITE, (int(self.pos.x), int(self.pos.y)), 2)

    def draw_ufo(self, surf: pygame.Surface, color_a: Color, color_b: Color) -> None:
        # "UFO" is a simple sharp triangle, as requested.
        r = 28
        points = [Vec2(r, 0), Vec2(-r * 0.78, -r * 0.82), Vec2(-r * 0.52, r * 0.92)]
        rad = math.radians(self.rotation)
        rot = []
        for p in points:
            q = Vec2(p.x * math.cos(rad) - p.y * math.sin(rad), p.x * math.sin(rad) + p.y * math.cos(rad))
            rot.append((self.pos.x + q.x, self.pos.y + q.y))

        draw_glow_circle(surf, (int(self.pos.x), int(self.pos.y)), 32, color_b, layers=2)
        pygame.draw.polygon(surf, color_b, rot)
        inner = []
        for x, y in rot:
            inner.append((lerp(x, self.pos.x, 0.20), lerp(y, self.pos.y, 0.20)))
        pygame.draw.polygon(surf, color_a, inner)
        pygame.draw.polygon(surf, WHITE, rot, 3)

        # Middle attachment dot.
        pygame.draw.circle(surf, BLACK, (int(self.pos.x), int(self.pos.y)), 5)
        pygame.draw.circle(surf, WHITE, (int(self.pos.x), int(self.pos.y)), 2)

    def draw_alt(self, surf: pygame.Surface, color_a: Color, color_b: Color) -> None:
        x, y = int(self.pos.x), int(self.pos.y)
        draw_glow_circle(surf, (x, y), 25, color_b, layers=2)
        if self.mode == "ship":
            pts = [(x + 29, y), (x - 21, y - 18), (x - 13, y), (x - 21, y + 18)]
            pygame.draw.polygon(surf, color_a, pts)
            pygame.draw.polygon(surf, WHITE, pts, 3)
            flame = 18 + (10 if self.thrusting else 0)
            pygame.draw.polygon(surf, ORANGE, [(x - 16, y - 7), (x - 16 - flame, y), (x - 16, y + 7)])
        elif self.mode == "ball":
            pygame.draw.circle(surf, color_a, (x, y), 23)
            pygame.draw.circle(surf, WHITE, (x, y), 23, 3)
            a = math.radians(self.rotation)
            pygame.draw.line(surf, WHITE, (x, y), (x + int(18 * math.cos(a)), y + int(18 * math.sin(a))), 5)
        elif self.mode == "wave":
            pts = [(x + 28, y), (x - 18, y - 20), (x - 8, y), (x - 18, y + 20)]
            pygame.draw.polygon(surf, color_a, pts)
            pygame.draw.polygon(surf, WHITE, pts, 3)
        elif self.mode == "swing":
            pygame.draw.circle(surf, color_a, (x, y), 21)
            pygame.draw.circle(surf, WHITE, (x, y), 21, 3)
            wing_y = 14 * self.gravity_dir
            pygame.draw.polygon(surf, color_b, [(x - 20, y), (x - 36, y - wing_y), (x - 13, y + wing_y)])
            pygame.draw.polygon(surf, color_b, [(x + 20, y), (x + 36, y - wing_y), (x + 13, y + wing_y)])
            pygame.draw.circle(surf, BLACK, (x, y), 6)
        elif self.mode == "robot":
            body = pygame.Rect(x - 20, y - 22, 40, 40)
            pygame.draw.rect(surf, color_a, body, border_radius=8)
            pygame.draw.rect(surf, WHITE, body, 3, border_radius=8)
            pygame.draw.circle(surf, BLACK, (x - 8, y - 5), 4)
            pygame.draw.circle(surf, BLACK, (x + 8, y - 5), 4)
            pygame.draw.line(surf, WHITE, (x - 12, y + 24), (x - 18, y + 31), 5)
            pygame.draw.line(surf, WHITE, (x + 12, y + 24), (x + 18, y + 31), 5)
        else:  # spider
            pygame.draw.polygon(surf, color_a, [(x, y - 23), (x + 23, y), (x, y + 23), (x - 23, y)])
            pygame.draw.polygon(surf, WHITE, [(x, y - 23), (x + 23, y), (x, y + 23), (x - 23, y)], 3)
            for sy in (-14, 14):
                pygame.draw.line(surf, WHITE, (x - 13, y + sy // 2), (x - 28, y + sy), 3)
                pygame.draw.line(surf, WHITE, (x + 13, y + sy // 2), (x + 28, y + sy), 3)

    def draw(self, surf: pygame.Surface, color_a: Color, color_b: Color, time_s: float) -> None:
        if self.trail_visible:
            self.trail.draw(surf, color_b, color_a, time_s)
        if self.invuln > 0 and int(self.invuln * 18) % 2 == 0:
            return
        if self.mode == "cube":
            self.draw_cube(surf, color_a, color_b)
        elif self.mode == "ufo":
            self.draw_ufo(surf, color_a, color_b)
        else:
            self.draw_alt(surf, color_a, color_b)


class Obstacle:
    def __init__(self, kind: str, x: float, speed: float, theme: Color):
        self.kind = kind
        self.x = x
        self.speed = speed
        self.theme = theme
        self.dead = False
        self.age = 0.0
        self.passed_player = False
        self.shots_fired = 0
        self.width = {"single": 38, "double": 78, "triple": 116, "quadruple": 154,
                      "block": 54, "moving_block": 58, "pendulum": 70,
                      "spinner": 150, "rotating_cross": 170, "crusher": 62,
                      "needle_gate": 74, "open_needle_gate": 74,
                      "laser_gate": 42, "chomper_high": 82,
                      "chomper_low": 82, "saw": 56}.get(kind, 46)

    def update(self, dt: float) -> bool:
        self.age += dt
        self.x -= self.speed * dt
        if self.x < -120:
            self.dead = True
        return not self.dead

    def spike_polys(self) -> List[List[Tuple[float, float]]]:
        polys: List[List[Tuple[float, float]]] = []
        if self.kind == "single":
            w, h = 38, 54
            polys.append([(self.x, GROUND_Y), (self.x + w / 2, GROUND_Y - h), (self.x + w, GROUND_Y)])
        elif self.kind == "double":
            w, h = 36, 52
            for i in range(2):
                x = self.x + i * 38
                polys.append([(x, GROUND_Y), (x + w / 2, GROUND_Y - h), (x + w, GROUND_Y)])
        elif self.kind == "triple":
            for i in range(3):
                x = self.x + i * 38
                polys.append([(x, GROUND_Y), (x + 18, GROUND_Y - 58), (x + 36, GROUND_Y)])
        elif self.kind == "quadruple":
            for i in range(4):
                x = self.x + i * 38
                height = 64 if i in (1, 2) else 55
                polys.append([(x, GROUND_Y), (x + 18, GROUND_Y - height), (x + 36, GROUND_Y)])
        elif self.kind.startswith("air"):
            y_map = {"air_low": 410, "air_mid": 315, "air_high": 220}
            y = y_map[self.kind]
            r = 28
            # Sharp floating triangle shard.
            polys.append([(self.x + r, y), (self.x - r, y - r * 0.9), (self.x - r * 0.72, y + r * 0.95)])
        elif self.kind == "ceiling":
            w, h = 42, 58
            polys.append([(self.x, 64), (self.x + w / 2, 64 + h), (self.x + w, 64)])
        elif self.kind == "block":
            polys.append([(self.x, GROUND_Y), (self.x, GROUND_Y - 76), (self.x + 54, GROUND_Y - 76), (self.x + 54, GROUND_Y)])
        elif self.kind in ("saw", "saw_mid", "moving_saw"):
            y = GROUND_Y - 28 if self.kind == "saw" else 300
            if self.kind == "moving_saw":
                y = 290 + math.sin(self.age * 4.2) * 125
            pts = []
            for i in range(16):
                a = i * math.tau / 16
                r = 32 if i % 2 == 0 else 20
                pts.append((self.x + math.cos(a) * r, y + math.sin(a) * r))
            polys.append(pts)
        elif self.kind == "moving_block":
            y = 300 + math.sin(self.age * 3.4) * 115
            polys.append([(self.x - 28, y - 28), (self.x + 28, y - 28),
                          (self.x + 28, y + 28), (self.x - 28, y + 28)])
        elif self.kind == "pendulum":
            cx = self.x + math.sin(self.age * 2.8) * 92
            cy = 165 + abs(math.cos(self.age * 2.8)) * 195
            pts = []
            for i in range(16):
                a = i * math.tau / 16
                r = 34 if i % 2 == 0 else 21
                pts.append((cx + math.cos(a) * r, cy + math.sin(a) * r))
            polys.append(pts)
        elif self.kind == "spinner":
            angle = self.age * 4.8
            for direction in (-1, 1):
                cx = self.x + math.cos(angle) * 68 * direction
                cy = 300 + math.sin(angle) * 68 * direction
                polys.append([(cx, cy - 24), (cx + 24, cy), (cx, cy + 24), (cx - 24, cy)])
        elif self.kind == "crusher":
            center = 292 + math.sin(self.age * 3.1) * 54
            half_gap = 82 + math.sin(self.age * 6.2) * 18
            left, right = self.x - 31, self.x + 31
            polys.append([(left, 64), (right, 64), (right, center - half_gap), (left, center - half_gap)])
            polys.append([(left, center + half_gap), (right, center + half_gap),
                          (right, GROUND_Y), (left, GROUND_Y)])
        elif self.kind == "needle_gate":
            center = 292 + math.sin(self.age * 4.0) * 68
            gap = 105
            for i in range(3):
                x = self.x - 33 + i * 23
                polys.append([(x, 64), (x + 21, 64), (x + 10, center - gap)])
                polys.append([(x, GROUND_Y), (x + 21, GROUND_Y), (x + 10, center + gap)])
        elif self.kind == "open_needle_gate":
            # Level 8's second gate deliberately leaves a broad lower route.
            # The preceding Ball portal no longer demands an instant flip.
            tip_y = 325 + math.sin(self.age * 3.0) * 22
            for i in range(3):
                x = self.x - 33 + i * 23
                polys.append([(x, 64), (x + 21, 64), (x + 10, tip_y)])
        elif self.kind == "rotating_cross":
            angle = self.age * 5.8
            for arm in range(4):
                a = angle + arm * math.pi / 2
                cx = self.x + math.cos(a) * 72
                cy = 300 + math.sin(a) * 72
                polys.append([(cx, cy - 21), (cx + 21, cy), (cx, cy + 21), (cx - 21, cy)])
        elif self.kind == "laser_gate":
            active = math.sin(self.age * 8.0 + 1.0) > -0.15
            if active:
                # A broad, slowly moving opening makes the laser demanding but
                # always passable. The lower route is safe for grounded forms.
                center = 430 + math.sin(self.age * 2.0) * 30
                half_gap = 105
                top_end = center - half_gap
                bottom_start = center + half_gap
                polys.append([(self.x - 10, 70), (self.x + 10, 70),
                              (self.x + 10, top_end), (self.x - 10, top_end)])
                if bottom_start < GROUND_Y:
                    polys.append([(self.x - 10, bottom_start), (self.x + 10, bottom_start),
                                  (self.x + 10, GROUND_Y), (self.x - 10, GROUND_Y)])
        elif self.kind.startswith("chomper_"):
            y = 245 if self.kind == "chomper_high" else 410
            polys.append([(self.x - 52, y - 40), (self.x + 48, y - 40),
                          (self.x + 48, y + 40), (self.x - 52, y + 40)])
        return polys

    def collides(self, rect: pygame.Rect) -> bool:
        for poly in self.spike_polys():
            if rect_touches_poly_rough(rect, poly, shrink=12):
                return True
        return False

    def draw(self, surf: pygame.Surface, time_s: float) -> None:
        if self.kind == "pendulum":
            cx = self.x + math.sin(self.age * 2.8) * 92
            cy = 165 + abs(math.cos(self.age * 2.8)) * 195
            pygame.draw.line(surf, (115, 125, 155), (int(self.x), 62), (int(cx), int(cy)), 6)
            pygame.draw.circle(surf, WHITE, (int(self.x), 62), 8, 2)
        elif self.kind == "spinner":
            pygame.draw.circle(surf, self.theme, (int(self.x), 300), 13)
            pygame.draw.circle(surf, WHITE, (int(self.x), 300), 13, 2)
            angle = self.age * 4.8
            for direction in (-1, 1):
                end = (int(self.x + math.cos(angle) * 68 * direction),
                       int(300 + math.sin(angle) * 68 * direction))
                pygame.draw.line(surf, self.theme, (int(self.x), 300), end, 5)
        elif self.kind == "moving_block":
            y = 300 + math.sin(self.age * 3.4) * 115
            pygame.draw.line(surf, (*self.theme,), (int(self.x), 170), (int(self.x), 430), 2)
        elif self.kind == "rotating_cross":
            pygame.draw.circle(surf, WHITE, (int(self.x), 300), 15, 3)
            angle = self.age * 5.8
            for arm in range(4):
                a = angle + arm * math.pi / 2
                end = (int(self.x + math.cos(a) * 72), int(300 + math.sin(a) * 72))
                pygame.draw.line(surf, self.theme, (int(self.x), 300), end, 6)
        elif self.kind == "laser_gate":
            charge = (math.sin(self.age * 8.0 + 1.0) + 1) / 2
            width = 3 + int(charge * 12)
            color = WHITE if charge > 0.43 else RED
            center = 430 + math.sin(self.age * 2.0) * 30
            half_gap = 105
            top_end = int(center - half_gap)
            bottom_start = int(center + half_gap)
            pygame.draw.line(surf, color, (int(self.x), 70), (int(self.x), top_end), width)
            if bottom_start < GROUND_Y:
                pygame.draw.line(surf, color, (int(self.x), bottom_start),
                                 (int(self.x), GROUND_Y), width)
            pygame.draw.circle(surf, GREEN, (int(self.x), int(center)), 13, 3)
            pygame.draw.line(surf, GREEN, (int(self.x - 26), int(center)),
                             (int(self.x + 26), int(center)), 3)
            draw_glow_circle(surf, (int(self.x), 84), 13, RED, 2)
        elif self.kind.startswith("chomper_"):
            y = 245 if self.kind == "chomper_high" else 410
            x = self.x
            jaw = 11 + abs(math.sin(self.age * 7.0)) * 16
            attack_charge = clamp((self.age - 0.42) / 0.18, 0, 1) if self.shots_fired == 0 else pulse(self.age, 10)

            # Neon aura and rear propulsion fins.
            draw_glow_circle(surf, (int(x + 10), y), 48, self.theme, 4)
            fin_color = tuple(int(lerp(self.theme[i], ORANGE[i], 0.35)) for i in range(3))
            upper_fin = [(x + 23, y - 22), (x + 61, y - 43), (x + 49, y - 5)]
            lower_fin = [(x + 23, y + 22), (x + 61, y + 43), (x + 49, y + 5)]
            pygame.draw.polygon(surf, fin_color, upper_fin)
            pygame.draw.polygon(surf, fin_color, lower_fin)
            pygame.draw.polygon(surf, WHITE, upper_fin, 2)
            pygame.draw.polygon(surf, WHITE, lower_fin, 2)

            # Layered armored skull.
            shell = [(x - 7, y - 39), (x + 29, y - 34), (x + 48, y - 12),
                     (x + 45, y + 21), (x + 22, y + 38), (x - 12, y + 32)]
            pygame.draw.polygon(surf, (24, 28, 48), shell)
            pygame.draw.polygon(surf, self.theme, shell, 5)
            inner_shell = [(lerp(px, x + 15, .28), lerp(py, y, .28)) for px, py in shell]
            pygame.draw.polygon(surf, tuple(int(c * .65) for c in self.theme), inner_shell, 3)

            # Dark mouth cavity faces left toward the player.
            mouth = [(x - 50, y), (x + 14, y - 17), (x + 22, y),
                     (x + 14, y + 17)]
            pygame.draw.polygon(surf, (3, 4, 10), mouth)
            throat_color = YELLOW if attack_charge > .65 else PINK
            draw_glow_circle(surf, (int(x - 2), y), int(7 + attack_charge * 7), throat_color, 2)
            pygame.draw.circle(surf, WHITE, (int(x - 2), y), 4)

            # Articulated upper and lower jaw plates.
            upper_jaw = [(x - 53, y - 3), (x - 39, y - jaw), (x + 17, y - 27),
                         (x + 26, y - 10), (x + 9, y - 6)]
            lower_jaw = [(x - 53, y + 3), (x - 39, y + jaw), (x + 17, y + 27),
                         (x + 26, y + 10), (x + 9, y + 6)]
            for plate in (upper_jaw, lower_jaw):
                pygame.draw.polygon(surf, self.theme, plate)
                pygame.draw.polygon(surf, WHITE, plate, 2)

            # Teeth taper toward the mouth opening.
            for tooth in range(4):
                tx = x - 39 + tooth * 15
                size = 9 if tooth < 2 else 7
                pygame.draw.polygon(surf, WHITE,
                                    [(tx, y - 5), (tx + 5, y + size), (tx + 10, y - 5)])
                pygame.draw.polygon(surf, WHITE,
                                    [(tx, y + 5), (tx + 5, y - size), (tx + 10, y + 5)])

            # Expressive targeting eye and small armor rivets.
            eye = (int(x + 18), y - 17)
            pygame.draw.circle(surf, BLACK, eye, 10)
            pygame.draw.circle(surf, RED, eye, 7)
            pygame.draw.circle(surf, WHITE, (eye[0] - 2, eye[1] - 2), 2)
            pygame.draw.line(surf, WHITE, (int(x + 5), y - 29), (int(x + 32), y - 25), 3)
            for ry in (-25, 25):
                pygame.draw.circle(surf, WHITE, (int(x + 35), y + ry), 3)
        for poly in self.spike_polys():
            if self.kind.startswith("chomper_"):
                continue
            # Glow
            p_rect = polygon_rect(poly).inflate(24, 24)
            glow = pygame.Surface((p_rect.w, p_rect.h), pygame.SRCALPHA)
            moved = [(x - p_rect.x, y - p_rect.y) for x, y in poly]
            pygame.draw.polygon(glow, (*self.theme, 45), moved)
            surf.blit(glow, (p_rect.x, p_rect.y), special_flags=pygame.BLEND_PREMULTIPLIED)

            pygame.draw.polygon(surf, self.theme, poly)
            pygame.draw.polygon(surf, WHITE, poly, 2)

            # Inner shine line.
            cx = sum(x for x, _ in poly) / len(poly)
            cy = sum(y for _, y in poly) / len(poly)
            tip = min(poly, key=lambda p: p[1]) if self.kind in ("single", "double") else max(poly, key=lambda p: p[0])
            pygame.draw.line(surf, (255, 255, 255), (int(cx), int(cy)), (int(tip[0]), int(tip[1])), 1)


class DeterrenceProjectile:
    def __init__(self, kind: str, origin: Vec2, target: Vec2):
        self.kind = kind
        self.pos = Vec2(origin)
        self.origin_x = origin.x
        self.y = origin.y
        self.age = 0.0
        self.dead = False
        if kind == "fire":
            direction = Vec2(target) - self.pos
            if direction.length_squared() == 0:
                direction = Vec2(-1, 0)
            self.vel = direction.normalize() * 560
        else:
            self.vel = Vec2()

    def update(self, dt: float) -> bool:
        self.age += dt
        if self.kind == "fire":
            self.pos += self.vel * dt
            self.vel.y += 90 * dt
            self.dead = self.pos.x < -50 or self.pos.y < -50 or self.pos.y > HEIGHT + 50
        else:
            self.dead = self.age > 0.72
        return not self.dead

    def collides(self, rect: pygame.Rect) -> bool:
        if self.kind == "fire":
            return rect.collidepoint(int(self.pos.x), int(self.pos.y)) or Vec2(rect.center).distance_to(self.pos) < 25
        # First quarter-second is a harmless telegraph.
        if not 0.24 <= self.age <= 0.62:
            return False
        beam = pygame.Rect(0, int(self.y - 10), int(max(0, self.origin_x)), 20)
        return rect.colliderect(beam)

    def draw(self, surf: pygame.Surface, time_s: float) -> None:
        if self.kind == "fire":
            tail = self.pos - self.vel.normalize() * 34 if self.vel.length_squared() else self.pos
            pygame.draw.line(surf, ORANGE, (int(tail.x), int(tail.y)),
                             (int(self.pos.x), int(self.pos.y)), 11)
            draw_glow_circle(surf, (int(self.pos.x), int(self.pos.y)), 13, RED, 3)
            pygame.draw.circle(surf, YELLOW, (int(self.pos.x), int(self.pos.y)), 8)
        else:
            telegraph = self.age < 0.24
            color = PINK if telegraph else WHITE
            width = 3 if telegraph else 15
            pygame.draw.line(surf, color, (0, int(self.y)), (int(self.origin_x), int(self.y)), width)
            if telegraph and int(self.age * 30) % 2 == 0:
                label = cached_font("arialblack", 13).render("LASER INCOMING", True, RED)
                surf.blit(label, (20, int(self.y - 32)))


class Portal:
    def __init__(self, target: str, x: float, speed: float, theme: Color):
        self.target = target
        self.x = x
        # Every portal intersects the ground-running approach; the new mode can
        # then move freely through the full playfield.
        self.y = GROUND_Y - 58
        self.speed = speed
        self.theme = theme
        self.radius = 38
        self.used = False
        self.dead = False

    def update(self, dt: float) -> bool:
        self.x -= self.speed * dt
        if self.x < -90:
            self.dead = True
        return not self.dead

    def touches_player(self, player: Player) -> bool:
        # Portals are vertical gates, not small rings. A flying player should
        # never miss a required mode transition merely for being high on screen.
        return abs(self.x - player.pos.x) < self.radius + 24

    def draw(self, surf: pygame.Surface, time_s: float) -> None:
        wobble = int(5 * pulse(time_s, 6, -1, 1))
        center = (int(self.x), int(self.y))
        colors = {"cube": CYAN, "ufo": PURPLE, "ship": ORANGE, "ball": GREEN,
                  "wave": YELLOW, "robot": BLUE, "spider": PINK, "swing": RED}
        color = colors.get(self.target, CYAN)
        beam = pygame.Surface((36, GROUND_Y - 55), pygame.SRCALPHA)
        pygame.draw.rect(beam, (*color, 28), beam.get_rect(), border_radius=18)
        surf.blit(beam, (int(self.x - 18), 55))
        draw_glow_circle(surf, center, self.radius + wobble, color, layers=4)
        pygame.draw.circle(surf, WHITE, center, self.radius + wobble, 2)
        label_font = cached_font("arialblack", 13)
        label = label_font.render(self.target.upper(), True, WHITE)
        surf.blit(label, label.get_rect(center=(center[0], center[1] - self.radius - 15)))

        # Compact target glyph.
        if self.target in ("ufo", "ship", "wave", "swing"):
            pts = [(self.x + 16, self.y), (self.x - 12, self.y - 16), (self.x - 12, self.y + 16)]
            pygame.draw.polygon(surf, color, pts)
            pygame.draw.polygon(surf, WHITE, pts, 2)
        elif self.target == "ball":
            pygame.draw.circle(surf, color, center, 15)
            pygame.draw.circle(surf, WHITE, center, 15, 2)
        else:
            r = pygame.Rect(0, 0, 28, 28)
            r.center = center
            pygame.draw.rect(surf, color, r, border_radius=5)
            pygame.draw.rect(surf, WHITE, r, 2, border_radius=5)


class PulseOrb:
    """A contextual tap target: yellow boosts, blue flips gravity."""

    def __init__(self, kind: str, x: float, speed: float):
        self.kind = kind
        self.x = x
        self.y = 345 if kind == "orb_yellow" else 270
        self.speed = speed
        self.used = False
        self.warned = False

    def update(self, dt: float) -> bool:
        self.x -= self.speed * dt
        return self.x > -60 and not self.used

    def attract_to(self, player: Player, dt: float) -> None:
        # Orbs slide toward the player's lane shortly before the tap window.
        # Horizontal timing is still required, but no form is locked out merely
        # because its natural resting height differs from the orb's spawn lane.
        horizontal = abs(self.x - player.pos.x)
        if horizontal < 155:
            strength = clamp(1 - horizontal / 155, 0, 1)
            self.y = lerp(self.y, player.pos.y, min(1, dt * (3.5 + strength * 9)))

    def can_activate(self, player: Player) -> bool:
        return abs(self.x - player.pos.x) < 88 and abs(self.y - player.pos.y) < 240

    def activate(self, player: Player) -> None:
        self.used = True
        if self.kind == "orb_blue":
            player.gravity_dir *= -1
            player.vel.y = 620 * player.gravity_dir
        else:
            player.vel.y = -930
            player.on_ground = False

    def draw(self, surf: pygame.Surface, time_s: float) -> None:
        color = YELLOW if self.kind == "orb_yellow" else BLUE
        radius = int(22 + pulse(time_s, 7, -2, 4))
        draw_glow_circle(surf, (int(self.x), int(self.y)), radius, color, 3)
        pygame.draw.circle(surf, (*color,), (int(self.x), int(self.y)), 36, 2)
        pygame.draw.circle(surf, WHITE, (int(self.x), int(self.y)), 7, 2)
        font = cached_font("arialblack", 12)
        label = font.render("TAP!", True, WHITE)
        surf.blit(label, label.get_rect(center=(int(self.x), int(self.y - 34))))


class CollectibleStar:
    def __init__(self, lane: str, x: float, speed: float):
        self.x = x
        # All three lanes are reachable by every grounded form. The old high
        # lane (205px) sat above cube's jump arc and was effectively impossible.
        self.y = {"low": 455, "mid": 365, "high": 290}.get(lane, 365)
        self.speed = speed
        self.rotation = 0.0
        self.collected = False

    def update(self, dt: float) -> bool:
        self.x -= self.speed * dt
        self.rotation += 150 * dt
        return self.x > -50 and not self.collected

    def attract_to(self, player: Player, dt: float) -> None:
        # A modest magnet catches intentional near-misses while still requiring
        # the player to enter the star's lane.
        distance = Vec2(self.x, self.y).distance_to(player.pos)
        if distance < 125:
            strength = clamp(1 - distance / 125, 0, 1)
            self.y = lerp(self.y, player.pos.y, min(1, dt * (5 + strength * 10)))

    def touches(self, player: Player) -> bool:
        return Vec2(self.x, self.y).distance_to(player.pos) < 62

    def draw(self, surf: pygame.Surface, time_s: float) -> None:
        outer, inner = 22 + pulse(time_s, 6, -2, 2), 9
        points = []
        for i in range(10):
            angle = math.radians(self.rotation - 90 + i * 36)
            radius = outer if i % 2 == 0 else inner
            points.append((self.x + math.cos(angle) * radius, self.y + math.sin(angle) * radius))
        draw_glow_circle(surf, (int(self.x), int(self.y)), 25, YELLOW, 3)
        pygame.draw.polygon(surf, YELLOW, points)
        pygame.draw.polygon(surf, WHITE, points, 2)


class FloatingText:
    def __init__(self, text: str, pos: Tuple[int, int], color: Color):
        self.text = text
        self.pos = Vec2(pos)
        self.color = color
        self.life = 1.2
        self.max_life = 1.2

    def update(self, dt: float) -> bool:
        self.life -= dt
        self.pos.y -= 45 * dt
        return self.life > 0

    def draw(self, surf: pygame.Surface, font: pygame.font.Font) -> None:
        a = int(255 * clamp(self.life / self.max_life, 0, 1))
        img = font.render(self.text, True, self.color)
        img.set_alpha(a)
        surf.blit(img, img.get_rect(center=(int(self.pos.x), int(self.pos.y))))


# -------------------------------
# Game
# -------------------------------
class ChatDashGame:
    def __init__(self, *, skip_onboarding: bool = False, profile_path: Optional[Path] = None):
        pygame.mixer.pre_init(44100, -16, 1, 512)
        pygame.init()
        if pygame.mixer.get_init() is not None:
            pygame.mixer.set_num_channels(24)
        pygame.display.set_caption(f"ChatDash {VERSION} - Eight Forms, Maximum Neon")
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        self.gradient_surface = self.make_gradient_surface()
        self.clock = pygame.time.Clock()
        self.font_big = cached_font("arialblack", 56)
        self.font_med = cached_font("arialblack", 30)
        self.font_small = cached_font("arial", 20, True)
        self.font_tiny = cached_font("arial", 16, True)
        self.sound = SoundManager()
        self.music = MusicSequencer(self.sound)

        self.levels = build_levels()
        sanity_check_levels(self.levels)

        self.player = Player()
        self.profile_path = Path(profile_path) if profile_path is not None else DEFAULT_PROFILE_PATH
        self.profile = (
            UserProfile("Test", "Player")
            if skip_onboarding
            else self.load_profile()
        )
        self.name_fields = [self.profile.first_name, self.profile.last_name]
        self.active_name_field = 0
        self.instruction_page = 0
        self.personalization_color_index = max(
            0, ("CYAN", "PINK", "GREEN", "YELLOW").index(self.profile.color_name)
            if self.profile.color_name in ("CYAN", "PINK", "GREEN", "YELLOW") else 0
        )
        self.level_index = 0
        self.level_time = 0.0
        self.world_time = 0.0
        self.state = MENU if skip_onboarding or self.profile.complete else SIGN_IN
        self.prev_state = MENU
        self.spawn_cursor = 0
        self.obstacles: List[Obstacle] = []
        self.portals: List[Portal] = []
        self.orbs: List[PulseOrb] = []
        self.stars_collectibles: List[CollectibleStar] = []
        self.deterrence_projectiles: List[DeterrenceProjectile] = []
        self.particles: List[Particle] = []
        self.floaters: List[FloatingText] = []
        self.camera_shake = 0.0
        self.complete_timer = 0.0
        self.crash_timer = 0.0
        self.stars = self.make_stars()
        self.best_level = 0
        self.selected_level = 0
        self.input_held = False
        self.last_warning_second = -1
        self.stars_collected = 0
        self.orbs_collected = 0
        self.attempt_stars = 0
        self.attempt_orbs = 0
        self.attempt_obstacles_dodged = 0
        self.attempt_projectiles_dodged = 0
        self.boundary_sound_cooldown = 0.0
        self.message_cursor = 0
        self.system_message = ""
        self.system_message_timer = 0.0
        self.security_alert = 0.0
        self.security_reactions: set[int] = set()
        self.security_reaction_cooldown = 0.0
        self.level_deaths = [0 for _ in self.levels]
        self.level_best_survival = [0.0 for _ in self.levels]
        self.level_best_dodges = [0 for _ in self.levels]
        self.death_summary: Optional[dict[str, object]] = None
        self.running = True
        self.reset_confirm_open = False
        self.apply_profile()

    def make_stars(self) -> List[Tuple[float, float, float, float]]:
        rng = random.Random(7)
        stars = []
        for _ in range(95):
            x = rng.uniform(0, WIDTH)
            y = rng.uniform(20, GROUND_Y - 70)
            r = rng.uniform(1, 3)
            spd = rng.uniform(10, 46)
            stars.append((x, y, r, spd))
        return stars

    @staticmethod
    def make_gradient_surface() -> pygame.Surface:
        surface = pygame.Surface((WIDTH, HEIGHT))
        for y in range(HEIGHT):
            t = y / HEIGHT
            color = (
                int(lerp(8, 20, t)),
                int(lerp(10, 18, t)),
                int(lerp(27, 42, t)),
            )
            pygame.draw.line(surface, color, (0, y), (WIDTH, y))
        return surface

    def load_profile(self) -> UserProfile:
        try:
            data = json.loads(self.profile_path.read_text(encoding="utf-8"))
            if not data.get("onboarding_complete"):
                return UserProfile()
            profile = UserProfile(
                first_name=str(data.get("first_name", ""))[:20],
                last_name=str(data.get("last_name", ""))[:20],
                color_name=str(data.get("color_name", "CYAN")).upper(),
                screen_shake=bool(data.get("screen_shake", True)),
                trails=bool(data.get("trails", True)),
            )
            return profile if profile.complete else UserProfile()
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return UserProfile()

    def save_profile(self) -> None:
        try:
            self.profile_path.write_text(
                json.dumps(self.profile.to_dict(), indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError:
            # A read-only install should not prevent the game from running.
            pass

    def apply_profile(self) -> None:
        if self.profile.color_name not in PROFILE_COLORS:
            self.profile.color_name = "CYAN"
        self.player.trail_visible = self.profile.trails

    @property
    def profile_color(self) -> Color:
        return PROFILE_COLORS.get(self.profile.color_name, CYAN)

    @property
    def level(self) -> Level:
        return self.levels[self.level_index]

    def reset_level(self, preserve_collectibles: bool = False) -> None:
        if not preserve_collectibles:
            self.stars_collected = max(0, self.stars_collected - self.attempt_stars)
            self.orbs_collected = max(0, self.orbs_collected - self.attempt_orbs)
        self.attempt_stars = 0
        self.attempt_orbs = 0
        self.attempt_obstacles_dodged = 0
        self.attempt_projectiles_dodged = 0
        self.level_time = 0.0
        self.spawn_cursor = 0
        self.obstacles.clear()
        self.portals.clear()
        self.orbs.clear()
        self.stars_collectibles.clear()
        self.deterrence_projectiles.clear()
        self.particles.clear()
        self.floaters.clear()
        self.camera_shake = 0.0
        self.crash_timer = 0.0
        self.complete_timer = 0.0
        self.player.reset()
        self.apply_profile()
        self.music.reset()
        self.input_held = False
        self.last_warning_second = -1
        self.boundary_sound_cooldown = 0.0
        self.message_cursor = 0
        self.system_message = ""
        self.system_message_timer = 0.0
        self.security_alert = 10.0 + self.level_index * 9.0
        self.security_reactions.clear()
        self.security_reaction_cooldown = 0.0
        self.death_summary = None
        self.state = PLAYING

    def open_level_select(self) -> None:
        self.selected_level = clamp(self.level_index, 0, len(self.levels) - 1)
        self.state = LEVEL_SELECT
        self.sound.play("select")

    def complete_sign_in(self) -> bool:
        first, last = (field.strip() for field in self.name_fields)
        if not first or not last:
            self.sound.play("warning")
            return False
        self.profile.first_name = first
        self.profile.last_name = last
        self.instruction_page = 0
        self.state = INSTRUCTIONS
        self.sound.play("checkpoint")
        return True

    def advance_instruction(self, direction: int = 1) -> None:
        page_count = 4
        new_page = self.instruction_page + direction
        if new_page >= page_count:
            self.state = PERSONALIZATION
        else:
            self.instruction_page = int(clamp(new_page, 0, page_count - 1))
        self.sound.play("select")

    def finish_personalization(self) -> None:
        names = tuple(PROFILE_COLORS)
        self.profile.color_name = names[self.personalization_color_index]
        self.apply_profile()
        self.save_profile()
        self.state = MENU
        self.sound.play("complete")

    @staticmethod
    def global_reset_rect() -> pygame.Rect:
        return pygame.Rect(WIDTH - 126, HEIGHT - 43, 108, 30)

    @staticmethod
    def reset_confirm_rects() -> Tuple[pygame.Rect, pygame.Rect]:
        return (
            pygame.Rect(WIDTH // 2 - 190, HEIGHT // 2 + 62, 170, 52),
            pygame.Rect(WIDTH // 2 + 20, HEIGHT // 2 + 62, 170, 52),
        )

    def reset_all_data(self) -> None:
        try:
            self.profile_path.unlink(missing_ok=True)
        except OSError:
            pass
        self.profile = UserProfile()
        self.name_fields = ["", ""]
        self.active_name_field = 0
        self.instruction_page = 0
        self.personalization_color_index = 0
        self.level_index = 0
        self.selected_level = 0
        self.best_level = 0
        self.level_time = 0.0
        self.spawn_cursor = 0
        self.stars_collected = 0
        self.orbs_collected = 0
        self.attempt_stars = 0
        self.attempt_orbs = 0
        self.attempt_obstacles_dodged = 0
        self.attempt_projectiles_dodged = 0
        self.level_deaths = [0 for _ in self.levels]
        self.level_best_survival = [0.0 for _ in self.levels]
        self.level_best_dodges = [0 for _ in self.levels]
        self.death_summary = None
        self.message_cursor = 0
        self.system_message = ""
        self.system_message_timer = 0.0
        self.security_alert = 0.0
        self.security_reactions.clear()
        self.camera_shake = 0.0
        self.complete_timer = 0.0
        self.crash_timer = 0.0
        self.boundary_sound_cooldown = 0.0
        self.obstacles.clear()
        self.portals.clear()
        self.orbs.clear()
        self.stars_collectibles.clear()
        self.deterrence_projectiles.clear()
        self.particles.clear()
        self.floaters.clear()
        self.player.reset()
        self.apply_profile()
        self.music.reset()
        self.input_held = False
        self.reset_confirm_open = False
        if self.sound.enabled:
            pygame.mixer.stop()
        self.state = SIGN_IN
        self.sound.play("start")

    @staticmethod
    def sign_in_field_rect(index: int) -> pygame.Rect:
        return pygame.Rect(WIDTH // 2 - 210, 242 + index * 92, 420, 60)

    @staticmethod
    def sign_in_continue_rect() -> pygame.Rect:
        return pygame.Rect(WIDTH // 2 - 150, 442, 300, 58)

    @staticmethod
    def instruction_back_rect() -> pygame.Rect:
        return pygame.Rect(72, HEIGHT - 82, 170, 50)

    @staticmethod
    def instruction_next_rect() -> pygame.Rect:
        return pygame.Rect(WIDTH - 350, HEIGHT - 82, 170, 50)

    @staticmethod
    def personalization_finish_rect() -> pygame.Rect:
        return pygame.Rect(WIDTH // 2 - 170, HEIGHT - 92, 340, 58)

    def change_selected_level(self, direction: int) -> None:
        self.selected_level = (int(self.selected_level) + direction) % len(self.levels)
        self.sound.play("select")

    def level_select_cards(self) -> List[Tuple[int, pygame.Rect, bool]]:
        cards: List[Tuple[int, pygame.Rect, bool]] = []
        selected = int(self.selected_level)
        for offset in range(-2, 3):
            index = (selected + offset) % len(self.levels)
            active = offset == 0
            size = (260, 285) if active else (155, 205)
            rect = pygame.Rect(0, 0, *size)
            rect.center = (WIDTH // 2 + offset * 190, 305)
            cards.append((index, rect, active))
        return cards

    def start_game(self) -> None:
        self.level_index = int(self.selected_level)
        self.stars_collected = 0
        self.orbs_collected = 0
        self.attempt_stars = 0
        self.attempt_orbs = 0
        self.reset_level()
        self.sound.play("start")

    @staticmethod
    def death_summary_close_rect() -> pygame.Rect:
        return pygame.Rect(WIDTH - 174, 82, 52, 52)

    @staticmethod
    def death_summary_back_rect() -> pygame.Rect:
        return pygame.Rect(120, HEIGHT - 112, 220, 48)

    def return_to_level_select(self) -> None:
        self.selected_level = int(clamp(self.level_index, 0, len(self.levels) - 1))
        self.death_summary = None
        self.input_held = False
        self.state = LEVEL_SELECT
        if self.sound.enabled:
            pygame.mixer.stop()
        self.sound.play("select")

    def emit_burst(self, pos: Vec2, color: Color, amount: int = 28, power: float = 260) -> None:
        for _ in range(amount):
            a = random.uniform(0, math.tau)
            s = random.uniform(60, power)
            vel = Vec2(math.cos(a) * s, math.sin(a) * s)
            self.particles.append(Particle(pos, vel, color, random.uniform(0.4, 0.9), random.uniform(2, 6)))

    def crash(self, cause: str = "OBSTACLE COLLISION") -> None:
        if self.state == CRASHED:
            return
        self.level_deaths[self.level_index] += 1
        total_dodged = self.attempt_obstacles_dodged + self.attempt_projectiles_dodged
        self.level_best_survival[self.level_index] = max(
            self.level_best_survival[self.level_index], self.level_time
        )
        self.level_best_dodges[self.level_index] = max(
            self.level_best_dodges[self.level_index], total_dodged
        )
        score = (
            int(self.level_time * 10)
            + self.attempt_obstacles_dodged * 100
            + self.attempt_projectiles_dodged * 140
            + self.attempt_stars * 250
            + self.attempt_orbs * 175
        )
        self.death_summary = {
            "level": self.level.name,
            "level_number": self.level_index + 1,
            "survived": self.level_time,
            "progress": clamp(self.level_time / LEVEL_LENGTH * 100, 0, 100),
            "obstacles": self.attempt_obstacles_dodged,
            "projectiles": self.attempt_projectiles_dodged,
            "stars": self.attempt_stars,
            "orbs": self.attempt_orbs,
            "score": score,
            "mode": self.player.mode.upper(),
            "alert": self.security_alert,
            "speed": self.level.speed,
            "bpm": self.level.bpm + self.level_index * 7,
            "deaths": self.level_deaths[self.level_index],
            "best_survival": self.level_best_survival[self.level_index],
            "best_dodges": self.level_best_dodges[self.level_index],
            "cause": cause,
        }
        self.state = CRASHED
        self.crash_timer = 0.0
        self.camera_shake = 18
        self.emit_burst(self.player.pos, RED, amount=44, power=430)
        self.floaters.append(FloatingText("RUN TERMINATED", (WIDTH // 2, 150), RED))
        self.sound.play("crash")

    def finish_level(self) -> None:
        self.state = LEVEL_COMPLETE
        self.complete_timer = 2.7
        self.camera_shake = 8
        self.best_level = max(self.best_level, self.level_index + 1)
        self.emit_burst(Vec2(WIDTH // 2, 180), self.level.theme_b, amount=75, power=360)
        self.sound.play("complete")

    def next_level(self) -> None:
        self.level_index += 1
        if self.level_index >= len(self.levels):
            self.state = WIN
            self.emit_burst(Vec2(WIDTH // 2, HEIGHT // 2), YELLOW, amount=120, power=430)
            self.sound.play("win")
        else:
            self.reset_level(preserve_collectibles=True)

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.QUIT:
            self.running = False
            return

        if self.reset_confirm_open:
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_RETURN, pygame.K_y):
                    self.reset_all_data()
                elif event.key in (pygame.K_ESCAPE, pygame.K_n):
                    self.reset_confirm_open = False
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                confirm, cancel = self.reset_confirm_rects()
                if confirm.collidepoint(event.pos):
                    self.reset_all_data()
                elif cancel.collidepoint(event.pos):
                    self.reset_confirm_open = False
            return

        if (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                and self.global_reset_rect().collidepoint(event.pos)):
            self.input_held = False
            self.reset_confirm_open = True
            self.sound.play("warning")
            return

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                if self.state == LEVEL_SELECT:
                    self.state = MENU
                    return
                if self.state == INSTRUCTIONS:
                    if self.instruction_page > 0:
                        self.advance_instruction(-1)
                    else:
                        self.state = SIGN_IN
                    return
                if self.state == PERSONALIZATION:
                    self.state = INSTRUCTIONS
                    self.instruction_page = 3
                    return
                self.running = False
                return
            if self.state == SIGN_IN:
                if event.key in (pygame.K_TAB, pygame.K_DOWN, pygame.K_UP):
                    self.active_name_field = 1 - self.active_name_field
                elif event.key == pygame.K_BACKSPACE:
                    self.name_fields[self.active_name_field] = self.name_fields[self.active_name_field][:-1]
                elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    if self.active_name_field == 0 and not self.name_fields[1].strip():
                        self.active_name_field = 1
                    else:
                        self.complete_sign_in()
                elif event.unicode and len(self.name_fields[self.active_name_field]) < 20:
                    if event.unicode.isalpha() or event.unicode in " -'":
                        self.name_fields[self.active_name_field] += event.unicode
                return
            if self.state == INSTRUCTIONS:
                if event.key in (pygame.K_LEFT, pygame.K_a):
                    self.advance_instruction(-1)
                elif event.key in (pygame.K_RIGHT, pygame.K_d, pygame.K_RETURN, pygame.K_SPACE):
                    self.advance_instruction(1)
                return
            if self.state == PERSONALIZATION:
                if event.key in (pygame.K_LEFT, pygame.K_a):
                    self.personalization_color_index = (
                        self.personalization_color_index - 1
                    ) % len(PROFILE_COLORS)
                elif event.key in (pygame.K_RIGHT, pygame.K_d):
                    self.personalization_color_index = (
                        self.personalization_color_index + 1
                    ) % len(PROFILE_COLORS)
                elif event.key == pygame.K_s:
                    self.profile.screen_shake = not self.profile.screen_shake
                elif event.key == pygame.K_t:
                    self.profile.trails = not self.profile.trails
                    self.apply_profile()
                elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                    self.finish_personalization()
                self.sound.play("select")
                return
            if self.state == LEVEL_SELECT:
                if event.key in (pygame.K_LEFT, pygame.K_a):
                    self.change_selected_level(-1)
                    return
                if event.key in (pygame.K_RIGHT, pygame.K_d, pygame.K_DOWN):
                    self.change_selected_level(1)
                    return
                if event.key == pygame.K_UP:
                    self.change_selected_level(-1)
                    return
                if pygame.K_1 <= event.key <= pygame.K_8:
                    self.selected_level = event.key - pygame.K_1
                    self.sound.play("select")
                    return
                if event.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_UP):
                    self.start_game()
                    return
            if self.state == PLAYING and event.key == pygame.K_p:
                self.prev_state = PLAYING
                self.state = PAUSED
                self.sound.play("pause")
                return
            if self.state == PAUSED and event.key == pygame.K_p:
                self.state = self.prev_state
                self.sound.play("start")
                return
            if event.key == pygame.K_m:
                self.sound.toggle_mute()
                return
            if event.key == pygame.K_r and self.state in (CRASHED, PLAYING, PAUSED):
                self.reset_level()
                return

            if event.key in (pygame.K_SPACE, pygame.K_UP):
                self.input_held = True
                if self.state == MENU:
                    self.open_level_select()
                elif self.state == PLAYING:
                    self.handle_action()
                elif self.state == WIN:
                    self.state = MENU
                elif self.state == LEVEL_COMPLETE and self.complete_timer < 1.25:
                    self.next_level()

        if event.type == pygame.KEYUP and event.key in (pygame.K_SPACE, pygame.K_UP):
            self.input_held = False

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.input_held = True
            if self.state == SIGN_IN:
                for index in range(2):
                    if self.sign_in_field_rect(index).collidepoint(event.pos):
                        self.active_name_field = index
                if self.sign_in_continue_rect().collidepoint(event.pos):
                    self.complete_sign_in()
            elif self.state == INSTRUCTIONS:
                if self.instruction_back_rect().collidepoint(event.pos):
                    if self.instruction_page == 0:
                        self.state = SIGN_IN
                    else:
                        self.advance_instruction(-1)
                elif self.instruction_next_rect().collidepoint(event.pos):
                    self.advance_instruction(1)
            elif self.state == PERSONALIZATION:
                for index in range(len(PROFILE_COLORS)):
                    swatch = pygame.Rect(305 + index * 110, 245, 76, 76)
                    if swatch.collidepoint(event.pos):
                        self.personalization_color_index = index
                        self.sound.play("select")
                if pygame.Rect(330, 362, 380, 54).collidepoint(event.pos):
                    self.profile.screen_shake = not self.profile.screen_shake
                    self.sound.play("select")
                elif pygame.Rect(330, 430, 380, 54).collidepoint(event.pos):
                    self.profile.trails = not self.profile.trails
                    self.apply_profile()
                    self.sound.play("select")
                elif self.personalization_finish_rect().collidepoint(event.pos):
                    self.finish_personalization()
            elif self.state == MENU:
                self.open_level_select()
            elif self.state == LEVEL_SELECT:
                pos = event.pos
                if pygame.Rect(5, 250, 75, 110).collidepoint(pos):
                    self.change_selected_level(-1)
                elif pygame.Rect(WIDTH - 80, 250, 75, 110).collidepoint(pos):
                    self.change_selected_level(1)
                elif pygame.Rect(WIDTH // 2 - 155, 480, 310, 58).collidepoint(pos):
                    self.start_game()
                else:
                    for index, rect, active in self.level_select_cards():
                        if rect.collidepoint(pos):
                            if active:
                                self.start_game()
                            else:
                                self.selected_level = index
                                self.sound.play("select")
                            break
            elif self.state == PLAYING:
                self.handle_action()
            elif self.state == CRASHED:
                if self.death_summary_close_rect().collidepoint(event.pos):
                    self.reset_level()
                elif self.death_summary_back_rect().collidepoint(event.pos):
                    self.return_to_level_select()
            elif self.state == WIN:
                self.state = MENU
            elif self.state == LEVEL_COMPLETE and self.complete_timer < 1.25:
                self.next_level()
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.input_held = False

    def play_action_sound(self) -> None:
        sound = {
            "cube": "jump", "ufo": "flap", "robot": "robot",
            "ball": "gravity", "spider": "teleport", "swing": "gravity",
        }.get(self.player.mode)
        if sound:
            self.sound.play(sound)

    def raise_security_alert(self, amount: float) -> None:
        self.security_alert = clamp(self.security_alert + amount, 0, 100)
        if self.security_reaction_cooldown > 0:
            return
        reactions = (
            (35, "MOVEMENT SIGNATURE CONFIRMED"),
            (65, "ACTIVE RESISTANCE DETECTED"),
            (90, "ERASURE SEQUENCE ACTIVE"),
        )
        for threshold, text in reactions:
            if self.security_alert >= threshold and threshold not in self.security_reactions:
                self.security_reactions.add(threshold)
                self.system_message = text
                self.system_message_timer = 2.3
                self.security_reaction_cooldown = 2.0
                self.sound.play("alarm")
                self.sound.play("impact")
                self.camera_shake = max(self.camera_shake, 4 + threshold / 20)
                if threshold >= 65 and self.state == PLAYING:
                    kind = "chomper_high" if threshold == 65 else "chomper_low"
                    self.obstacles.append(Obstacle(kind, WIDTH + 100, self.level.speed, RED))
                    self.floaters.append(FloatingText("CHOMPER DEPLOYED!", (WIDTH // 2, 210), RED))
                break

    def handle_action(self) -> None:
        for orb in self.orbs:
            if not orb.used and orb.can_activate(self.player):
                orb.activate(self.player)
                self.raise_security_alert(9)
                self.orbs_collected += 1
                self.attempt_orbs += 1
                color = YELLOW if orb.kind == "orb_yellow" else BLUE
                self.emit_burst(Vec2(orb.x, orb.y), color, amount=34, power=280)
                self.sound.play("gravity" if orb.kind == "orb_blue" else "checkpoint")
                self.floaters.append(FloatingText("ORB ACTIVATED!", (WIDTH // 2, 145), color))
                return
        if self.player.action():
            self.raise_security_alert(3.5)
            self.play_action_sound()

    def spawn_events(self) -> None:
        events = self.level.events
        # Event timestamps represent the moment an object reaches the player.
        # Spawn early enough that visuals and the music share one exact clock.
        travel_time = (WIDTH + 60 - PLAYER_X) / self.level.speed
        while self.spawn_cursor < len(events) and events[self.spawn_cursor].t - travel_time <= self.level_time:
            ev = events[self.spawn_cursor]
            if ev.kind == "portal":
                self.portals.append(Portal(ev.target or "ufo", WIDTH + 70, self.level.speed, self.level.theme_b))
            elif ev.kind.startswith("orb_"):
                self.orbs.append(PulseOrb(ev.kind, WIDTH + 60, self.level.speed))
            elif ev.kind == "star":
                self.stars_collectibles.append(CollectibleStar(ev.lane, WIDTH + 60, self.level.speed))
            else:
                self.obstacles.append(Obstacle(ev.kind, WIDTH + 60, self.level.speed, self.level.theme_b))
                if ev.kind.startswith("chomper_"):
                    self.floaters.append(FloatingText("CHOMPER TURRET INBOUND!", (WIDTH // 2, 215), RED))
                    self.sound.play("chomp")
            self.spawn_cursor += 1

    def update_playing(self, dt: float) -> None:
        self.level_time += dt
        self.world_time += dt
        self.system_message_timer = max(0.0, self.system_message_timer - dt)
        self.security_reaction_cooldown = max(0.0, self.security_reaction_cooldown - dt)
        self.security_alert = clamp(
            self.security_alert + dt * (0.35 + self.level_index * 0.08), 0, 100
        )
        messages = INTRUDER_MESSAGES[self.level_index]
        while self.message_cursor < len(messages) and self.level_time >= messages[self.message_cursor][0]:
            _, self.system_message = messages[self.message_cursor]
            self.system_message_timer = 2.65
            self.message_cursor += 1
            self.sound.play("alarm")
            self.sound.play("impact" if self.level_index >= 5 else "warning")
            self.camera_shake = max(self.camera_shake, 2 + self.level_index * 0.75)
        self.spawn_events()
        self.music.update(self.level_time, self.level.bpm + self.level_index * 7, self.level.events, self.level_index)

        self.player.update(dt, self.input_held)
        self.boundary_sound_cooldown = max(0.0, self.boundary_sound_cooldown - dt)
        if self.player.just_landed:
            self.sound.play("land")
        if self.player.hit_boundary and self.boundary_sound_cooldown <= 0:
            self.sound.play("boundary")
            self.boundary_sound_cooldown = 0.14
        if self.input_held and self.player.mode in ("ship", "wave") and random.random() < 0.09:
            self.sound.play("boost")
        self.obstacles = [o for o in self.obstacles if o.update(dt)]
        for obstacle in self.obstacles:
            if obstacle.kind.startswith("chomper_"):
                shot_times = (0.58, 1.04)
                while obstacle.shots_fired < len(shot_times) and obstacle.age >= shot_times[obstacle.shots_fired]:
                    y = 245 if obstacle.kind == "chomper_high" else 410
                    kind = "fire" if obstacle.shots_fired == 0 else "laser"
                    self.deterrence_projectiles.append(
                        DeterrenceProjectile(kind, Vec2(obstacle.x - 54, y), self.player.pos)
                    )
                    obstacle.shots_fired += 1
                    self.sound.play("fire_spit" if kind == "fire" else "laser_blast")
                    self.sound.play("chomp")
            if not obstacle.passed_player and obstacle.x + obstacle.width < self.player.pos.x:
                obstacle.passed_player = True
                self.attempt_obstacles_dodged += 1
                self.sound.play("near_miss")
        active_projectiles: List[DeterrenceProjectile] = []
        for projectile in self.deterrence_projectiles:
            if projectile.update(dt):
                active_projectiles.append(projectile)
            else:
                self.attempt_projectiles_dodged += 1
        self.deterrence_projectiles = active_projectiles
        self.portals = [p for p in self.portals if p.update(dt)]
        active_orbs: List[PulseOrb] = []
        for orb in self.orbs:
            if orb.update(dt):
                if not orb.warned and abs(orb.x - self.player.pos.x) < 240:
                    orb.warned = True
                    self.sound.play("orb_near")
                orb.attract_to(self.player, dt)
                active_orbs.append(orb)
        self.orbs = active_orbs
        self.stars_collectibles = [s for s in self.stars_collectibles if s.update(dt)]
        self.particles = [p for p in self.particles if p.update(dt)]
        self.floaters = [f for f in self.floaters if f.update(dt)]
        self.camera_shake = max(0.0, self.camera_shake - 32 * dt)

        # Portal use.
        for portal in self.portals:
            if not portal.used and portal.touches_player(self.player):
                portal.used = True
                portal.dead = True
                self.player.set_mode(portal.target)
                self.raise_security_alert(4)
                self.sound.play("portal")
                self.sound.play("mode_warp")
                self.player.invuln = 0.25
                mode_colors = {"cube": CYAN, "ufo": PURPLE, "ship": ORANGE, "ball": GREEN,
                               "wave": YELLOW, "robot": BLUE, "spider": PINK, "swing": RED}
                color = mode_colors.get(portal.target, CYAN)
                self.emit_burst(Vec2(portal.x, portal.y), color, amount=46, power=340)
                self.floaters.append(FloatingText(f"{portal.target.upper()} MODE!", (WIDTH // 2, 110), color))
                if self.level_index == 7:
                    self.camera_shake = max(self.camera_shake, 7)

        self.portals = [p for p in self.portals if not p.dead]

        for star in self.stars_collectibles:
            star.attract_to(self.player, dt)
            if star.touches(self.player):
                star.collected = True
                self.raise_security_alert(8)
                self.stars_collected += 1
                self.attempt_stars += 1
                self.sound.play("star")
                self.emit_burst(Vec2(star.x, star.y), YELLOW, amount=30, power=240)
                self.floaters.append(FloatingText("STAR +1", (WIDTH // 2, 145), YELLOW))
        self.stars_collectibles = [s for s in self.stars_collectibles if not s.collected]

        # Collision.
        hit_rect = self.player.rect()
        if self.player.invuln <= 0:
            for obstacle in self.obstacles:
                if obstacle.collides(hit_rect):
                    cause = obstacle.kind.replace("_", " ").upper()
                    self.crash(f"HIT BY {cause}")
                    break
            if self.state == PLAYING:
                for projectile in self.deterrence_projectiles:
                    if projectile.collides(hit_rect):
                        cause = "CHOMPER FIREBALL" if projectile.kind == "fire" else "CHOMPER LASER"
                        self.crash(cause)
                        break

        if self.level_time >= LEVEL_LENGTH and self.state == PLAYING:
            self.finish_level()
        remain = int(LEVEL_LENGTH - self.level_time)
        if remain in (10, 5, 3, 2, 1) and remain != self.last_warning_second:
            self.last_warning_second = remain
            self.sound.play("warning")

    def update(self, dt: float) -> None:
        if self.state not in (PAUSED, PLAYING):
            self.world_time += dt
        if self.state == PLAYING:
            self.update_playing(dt)
        elif self.state == CRASHED:
            self.particles = [p for p in self.particles if p.update(dt)]
            self.floaters = [f for f in self.floaters if f.update(dt)]
            self.camera_shake = max(0.0, self.camera_shake - 40 * dt)
        elif self.state == LEVEL_COMPLETE:
            self.complete_timer -= dt
            self.particles = [p for p in self.particles if p.update(dt)]
            if self.complete_timer <= 0:
                self.next_level()
        elif self.state == WIN:
            self.particles = [p for p in self.particles if p.update(dt)]
            if random.random() < 0.18:
                self.emit_burst(Vec2(random.randint(120, WIDTH - 120), random.randint(90, 360)), random.choice([CYAN, PINK, YELLOW, GREEN]), amount=10, power=180)

    # -------------------------------
    # Drawing
    # -------------------------------
    def draw_background(self, surf: pygame.Surface) -> None:
        if self.state == LEVEL_SELECT:
            lvl = self.levels[int(self.selected_level)]
        else:
            lvl = self.level if self.state not in (MENU, WIN) else self.levels[min(self.level_index, len(self.levels) - 1)]
        surf.blit(self.gradient_surface, (0, 0))

        # stars / streaks
        for i, (x, y, r, spd) in enumerate(self.stars):
            xx = (x - self.world_time * spd) % (WIDTH + 40) - 20
            tw = pulse(self.world_time + i, 2.3, 0.35, 1.0)
            col = tuple(int(lerp(80, lvl.theme_a[j], tw)) for j in range(3))
            pygame.draw.circle(surf, col, (int(xx), int(y)), int(r))
            if spd > 35:
                pygame.draw.line(surf, col, (int(xx), int(y)), (int(xx + 18), int(y)), 1)

        # moving grid
        grid_color = tuple(max(18, int(channel * 0.19)) for channel in lvl.theme_a)
        offset = int((self.world_time * lvl.speed * 0.33) % 48)
        for x in range(-offset, WIDTH, 48):
            pygame.draw.line(surf, grid_color, (x, 0), (x, GROUND_Y), 1)
        for y in range(80, GROUND_Y, 48):
            pygame.draw.line(surf, grid_color, (0, y), (WIDTH, y), 1)

        # The world visibly intensifies with progress: subtle color flashes,
        # speed lines, and a closing vignette make late sections feel urgent.
        intensity = clamp((self.level_time / LEVEL_LENGTH) if self.state in (PLAYING, CRASHED) else 0, 0, 1)
        if intensity > 0.48:
            streaks = int(4 + intensity * 14)
            for i in range(streaks):
                y = 90 + ((i * 83 + int(self.world_time * lvl.speed * (0.7 + i % 3 * .2))) % 370)
                length = int(25 + 100 * intensity)
                x = (i * 137 - int(self.world_time * lvl.speed * 1.4)) % (WIDTH + length)
                pygame.draw.line(surf, (*lvl.theme_b,), (x, y), (x + length, y), 1 + int(intensity))
        if intensity > 0.72 and pulse(self.world_time, 9) > 0.82:
            flash = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            flash.fill((*lvl.theme_b, int(16 * intensity)))
            surf.blit(flash, (0, 0))

        if self.level_index == 7 and self.state not in (MENU, WIN):
            # Level 8's reactor hangs in the distance and becomes increasingly
            # unstable: rotating rings, sweeping warning beams, and beat pulses.
            core = (WIDTH - 145, 250)
            beat = pulse(self.world_time, 12, 0.75, 1.25)
            draw_glow_circle(surf, core, int(52 * beat), RED, 5)
            pygame.draw.circle(surf, YELLOW, core, int(24 * beat))
            for ring in range(3):
                radius = 72 + ring * 31
                rect = pygame.Rect(0, 0, radius * 2, radius * 2)
                rect.center = core
                start = self.world_time * (1.8 + ring * .55) * (-1 if ring % 2 else 1)
                pygame.draw.arc(surf, (255, 90 + ring * 45, 45), rect, start, start + 3.8, 4)
            warning = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            sweep = int((math.sin(self.world_time * 1.7) + 1) * WIDTH / 2)
            pygame.draw.polygon(warning, (255, 45, 35, 22 + int(intensity * 35)),
                                [(core[0], core[1]), (sweep - 115, HEIGHT), (sweep + 115, HEIGHT)])
            surf.blit(warning, (0, 0))
            if int(self.world_time * 4) % 8 == 0:
                alert = self.font_tiny.render("⚠ REACTOR CRITICAL ⚠", True, RED)
                surf.blit(alert, alert.get_rect(center=(WIDTH // 2, 78)))
            for i in range(7):
                ax = int((i * 190 - self.world_time * 240) % (WIDTH + 120) - 60)
                ay = 120 + (i % 3) * 105
                chevron = [(ax - 18, ay - 14), (ax, ay), (ax - 18, ay + 14)]
                pygame.draw.lines(surf, (*YELLOW,), False, chevron, 4)

        # ground
        ground_rect = pygame.Rect(0, GROUND_Y, WIDTH, HEIGHT - GROUND_Y)
        pygame.draw.rect(surf, (16, 19, 31), ground_rect)
        pygame.draw.line(surf, lvl.theme_b, (0, GROUND_Y), (WIDTH, GROUND_Y), 4)
        pygame.draw.line(surf, WHITE, (0, GROUND_Y - 2), (WIDTH, GROUND_Y - 2), 1)
        for x in range(-offset, WIDTH, 48):
            pygame.draw.line(surf, (36, 40, 64), (x, GROUND_Y + 8), (x + 28, HEIGHT), 2)

    def draw_hud(self, surf: pygame.Surface) -> None:
        if self.state not in (PLAYING, PAUSED, CRASHED):
            return
        lvl = self.level
        # top progress bar
        bar_x, bar_y, bar_w, bar_h = 180, 22, 680, 16
        pygame.draw.rect(surf, (27, 31, 50), (bar_x, bar_y, bar_w, bar_h), border_radius=8)
        pct = clamp(self.level_time / LEVEL_LENGTH, 0, 1)
        pygame.draw.rect(surf, lvl.theme_b, (bar_x, bar_y, int(bar_w * pct), bar_h), border_radius=8)
        pygame.draw.rect(surf, WHITE, (bar_x, bar_y, bar_w, bar_h), 2, border_radius=8)

        title = self.font_small.render(lvl.name, True, WHITE)
        surf.blit(title, (22, 17))
        remain = max(0, int(math.ceil(LEVEL_LENGTH - self.level_time)))
        time_img = self.font_small.render(f"{remain:02d}s", True, lvl.theme_b)
        surf.blit(time_img, (880, 17))

        instructions = {
            "cube": "CUBE: TAP TO JUMP", "ufo": "UFO: TAP TO FLAP",
            "ship": "SHIP: HOLD TO RISE", "ball": "BALL: TAP TO FLIP GRAVITY",
            "wave": "WAVE: HOLD UP / RELEASE DOWN", "robot": "ROBOT: POWER JUMP",
            "spider": "SPIDER: TAP TO TELEPORT", "swing": "SWING: TAP TO FLIP GRAVITY",
        }
        mode_text = instructions[self.player.mode]
        mode_img = self.font_tiny.render(mode_text, True, lvl.theme_a)
        surf.blit(mode_img, (22, 48))
        loot = self.font_tiny.render(f"★ {self.stars_collected}    ORBS {self.orbs_collected}", True, YELLOW)
        surf.blit(loot, (WIDTH - loot.get_width() - 24, 48))

    def draw_music_notes(self, surf: pygame.Surface) -> None:
        if self.state not in (PLAYING, PAUSED, CRASHED) or not self.music.note_history:
            return
        panel = pygame.Surface((265, 112), pygame.SRCALPHA)
        panel.fill((8, 10, 24, 105))
        for line in range(5):
            y = 30 + line * 13
            pygame.draw.line(panel, (*self.level.theme_a, 115), (14, y), (250, y), 1)
        label = self.font_tiny.render(f"LIVE MELODY  {int(self.level.bpm + self.level_index * 7)} BPM", True, WHITE)
        panel.blit(label, (13, 5))

        for midi, born in self.music.note_history:
            age = self.level_time - born
            x = int(232 - age * 118)
            if x < 10:
                continue
            # Higher MIDI notes appear higher on the staff.
            y = int(clamp(82 - (midi - 44) * 2.0, 25, 88))
            alpha = int(255 * clamp(1 - age / 1.8, 0, 1))
            note_color = (*self.level.theme_b, alpha)
            pygame.draw.ellipse(panel, note_color, (x - 7, y - 5, 15, 10))
            pygame.draw.line(panel, note_color, (x + 6, y), (x + 6, y - 25), 3)
            pygame.draw.circle(panel, (*WHITE, alpha), (x, y), 3)
        surf.blit(panel, (WIDTH - 285, 82))

    def draw_intruder_message(self, surf: pygame.Surface) -> None:
        anger = (self.level_index + 1) / len(self.levels)
        status = pygame.Surface((250, 48), pygame.SRCALPHA)
        status.fill((8, 10, 24, 165))
        active_color = tuple(int(lerp(ORANGE[i], RED[i], anger)) for i in range(3))
        pygame.draw.rect(status, (*active_color, 230), status.get_rect(), 2, border_radius=8)
        label = self.font_tiny.render("SECURITY AI  //  ACTIVE", True, active_color)
        status.blit(label, (10, 5))
        pygame.draw.rect(status, (38, 42, 60), (10, 29, 228, 9), border_radius=4)
        pygame.draw.rect(status, active_color,
                         (10, 29, int(228 * self.security_alert / 100), 9), border_radius=4)
        surf.blit(status, (18, 78))

        if self.system_message_timer <= 0 or not self.system_message:
            return
        appear = clamp((2.65 - self.system_message_timer) * 5, 0, 1)
        fade = clamp(self.system_message_timer * 2, 0, 1)
        alpha = int(235 * min(appear, fade))
        width = 650 + int(anger * 170)
        panel = pygame.Surface((width, 76), pygame.SRCALPHA)
        panel.fill((18 + int(anger * 35), 5, 12, int(alpha * 0.82)))
        border = tuple(int(lerp(YELLOW[i], RED[i], anger)) for i in range(3))
        pygame.draw.rect(panel, (*border, alpha), panel.get_rect(), 4, border_radius=12)
        pygame.draw.line(panel, (*WHITE, alpha), (18, 12), (width - 18, 12), 2)

        font = self.font_med if len(self.system_message) < 31 else self.font_small
        message = font.render(self.system_message, True, WHITE)
        message.set_alpha(alpha)
        if self.level_index >= 5 and int(self.world_time * 18) % 5 == 0:
            glitch = font.render(self.system_message, True, RED)
            glitch.set_alpha(alpha // 2)
            panel.blit(glitch, glitch.get_rect(center=(width // 2 + 5, 43)))
        panel.blit(message, message.get_rect(center=(width // 2, 43)))
        y = int(lerp(135, 168, appear))
        surf.blit(panel, panel.get_rect(center=(WIDTH // 2, y)))

    @staticmethod
    def draw_dim_overlay(surf: pygame.Surface, alpha: int = 205) -> None:
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill((2, 4, 14, alpha))
        surf.blit(overlay, (0, 0))

    @staticmethod
    def draw_callout_arrow(
        surf: pygame.Surface, start: Tuple[int, int], target: Tuple[int, int], color: Color
    ) -> None:
        pygame.draw.line(surf, color, start, target, 5)
        direction = Vec2(start) - Vec2(target)
        if direction.length_squared() == 0:
            return
        direction = direction.normalize()
        perpendicular = Vec2(-direction.y, direction.x)
        tip = Vec2(target)
        left = tip + direction * 22 + perpendicular * 11
        right = tip + direction * 22 - perpendicular * 11
        pygame.draw.polygon(surf, color, [tip, left, right])
        pygame.draw.circle(surf, WHITE, target, 8, 2)

    def draw_sign_in(self, surf: pygame.Surface) -> None:
        self.draw_dim_overlay(surf, 218)
        title = self.font_big.render("WELCOME TO CHATDASH", True, WHITE)
        surf.blit(title, title.get_rect(center=(WIDTH // 2, 92)))
        subtitle = self.font_small.render(
            "Create your local player profile • no account or network required", True, CYAN
        )
        surf.blit(subtitle, subtitle.get_rect(center=(WIDTH // 2, 140)))

        panel = pygame.Rect(WIDTH // 2 - 270, 182, 540, 360)
        pygame.draw.rect(surf, (18, 22, 43), panel, border_radius=24)
        pygame.draw.rect(surf, CYAN, panel, 4, border_radius=24)
        heading = self.font_med.render("PLAYER SIGN IN", True, WHITE)
        surf.blit(heading, heading.get_rect(center=(WIDTH // 2, 200)))

        labels = ("FIRST NAME", "LAST NAME")
        for index, label_text in enumerate(labels):
            rect = self.sign_in_field_rect(index)
            active = index == self.active_name_field
            label = self.font_tiny.render(label_text, True, CYAN if active else (155, 166, 196))
            surf.blit(label, (rect.left, rect.top - 22))
            pygame.draw.rect(surf, (9, 12, 28), rect, border_radius=13)
            pygame.draw.rect(surf, CYAN if active else (65, 72, 98), rect, 3, border_radius=13)
            value = self.name_fields[index]
            shown = value if value else ("Type your first name" if index == 0 else "Type your last name")
            color = WHITE if value else (92, 101, 132)
            text = self.font_small.render(shown, True, color)
            surf.blit(text, (rect.left + 18, rect.centery - text.get_height() // 2))
            if active and int(self.world_time * 2) % 2 == 0:
                caret_x = rect.left + 20 + self.font_small.size(value)[0]
                pygame.draw.line(surf, WHITE, (caret_x, rect.top + 16), (caret_x, rect.bottom - 16), 2)

        button = self.sign_in_continue_rect()
        ready = bool(self.name_fields[0].strip() and self.name_fields[1].strip())
        button_color = CYAN if ready else (55, 63, 88)
        pygame.draw.rect(surf, button_color, button, border_radius=16)
        pygame.draw.rect(surf, WHITE if ready else (105, 113, 140), button, 2, border_radius=16)
        text = self.font_small.render("CONTINUE TO INSTRUCTIONS  →", True, BLACK if ready else WHITE)
        surf.blit(text, text.get_rect(center=button.center))
        privacy = self.font_tiny.render(
            "Saved only on this computer. Tab switches fields.", True, (140, 151, 181)
        )
        surf.blit(privacy, privacy.get_rect(center=(WIDTH // 2, 521)))

    def draw_instructions(self, surf: pygame.Surface) -> None:
        self.draw_dim_overlay(surf, 218)
        pages = (
            ("ONE BUTTON, MANY FORMS",
             "Tap SPACE, UP, or click. Your action changes with Cube, Ship, Ball, Wave, Robot, Spider, UFO, and Swing.",
             (188, 420), CYAN),
            ("READ THE LEVEL",
             "The top bar shows progress and time. Portal labels announce your next form before the transition arrives.",
             (520, 54), PURPLE),
            ("COLLECT & INTERACT",
             "Stars reward movement. When an orb says TAP, press near it to boost or flip gravity.",
             (175, 365), YELLOW),
            ("SECURITY IS ACTIVE",
             "The Security AI reacts to movement and deploys hazards. Watch telegraphs, warnings, lasers, and chomper attacks.",
             (178, 112), RED),
        )
        title_text, body_text, target, color = pages[self.instruction_page]

        # Draw the highlighted example that the callout arrow references.
        if self.instruction_page == 0:
            pygame.draw.rect(surf, self.profile_color, (target[0] - 24, target[1] - 24, 48, 48), border_radius=7)
            pygame.draw.rect(surf, WHITE, (target[0] - 24, target[1] - 24, 48, 48), 3, border_radius=7)
            pygame.draw.line(surf, CYAN, (40, target[1] + 30), (target[0] - 30, target[1]), 5)
        elif self.instruction_page == 1:
            pygame.draw.rect(surf, (28, 33, 55), (260, 42, 520, 24), border_radius=12)
            pygame.draw.rect(surf, color, (260, 42, 310, 24), border_radius=12)
            pygame.draw.rect(surf, WHITE, (260, 42, 520, 24), 2, border_radius=12)
        elif self.instruction_page == 2:
            draw_glow_circle(surf, target, 28, BLUE, 4)
            pygame.draw.circle(surf, WHITE, target, 10, 3)
            star = CollectibleStar("mid", target[0] - 105, 0)
            star.y = target[1]
            star.draw(surf, self.world_time)
        else:
            pygame.draw.rect(surf, (20, 24, 44), (45, 88, 266, 52), border_radius=10)
            pygame.draw.rect(surf, RED, (45, 88, 266, 52), 3, border_radius=10)
            active = self.font_tiny.render("SECURITY AI // ACTIVE", True, RED)
            surf.blit(active, (60, 98))
            pygame.draw.rect(surf, RED, (60, 122, 190, 8), border_radius=4)

        panel = pygame.Rect(320, 145, 650, 330)
        pygame.draw.rect(surf, (17, 21, 42), panel, border_radius=24)
        pygame.draw.rect(surf, color, panel, 4, border_radius=24)
        page_label = self.font_tiny.render(
            f"INSTRUCTIONS  •  PAGE {self.instruction_page + 1} OF {len(pages)}", True, color
        )
        surf.blit(page_label, (panel.left + 34, panel.top + 28))
        heading = self.font_med.render(title_text, True, WHITE)
        surf.blit(heading, (panel.left + 34, panel.top + 64))

        words = body_text.split()
        lines: List[str] = []
        line = ""
        for word in words:
            candidate = f"{line} {word}".strip()
            if self.font_small.size(candidate)[0] > panel.w - 68:
                lines.append(line)
                line = word
            else:
                line = candidate
        if line:
            lines.append(line)
        for index, line_text in enumerate(lines):
            rendered = self.font_small.render(line_text, True, (210, 218, 239))
            surf.blit(rendered, (panel.left + 34, panel.top + 125 + index * 31))

        arrow_start = (panel.left + 22, panel.bottom - 55)
        self.draw_callout_arrow(surf, arrow_start, target, color)
        for page in range(len(pages)):
            dot_color = color if page == self.instruction_page else (72, 79, 104)
            pygame.draw.circle(surf, dot_color, (WIDTH // 2 - 30 + page * 20, 508), 6)

        back = self.instruction_back_rect()
        nxt = self.instruction_next_rect()
        for rect, text_value in ((back, "← BACK"), (nxt, "PERSONALIZE →" if self.instruction_page == 3 else "NEXT →")):
            pygame.draw.rect(surf, (24, 30, 55), rect, border_radius=13)
            pygame.draw.rect(surf, color, rect, 3, border_radius=13)
            text = self.font_small.render(text_value, True, WHITE)
            surf.blit(text, text.get_rect(center=rect.center))

    def draw_personalization(self, surf: pygame.Surface) -> None:
        self.draw_dim_overlay(surf, 218)
        title = self.font_big.render("PERSONALIZATION", True, WHITE)
        surf.blit(title, title.get_rect(center=(WIDTH // 2, 76)))
        hello = self.font_small.render(
            f"Welcome, {self.profile.first_name}. Make ChatDash yours.", True, CYAN
        )
        surf.blit(hello, hello.get_rect(center=(WIDTH // 2, 124)))

        chosen_color = tuple(PROFILE_COLORS.values())[self.personalization_color_index]
        panel = pygame.Rect(250, 155, 540, 360)
        pygame.draw.rect(surf, (17, 21, 42), panel, border_radius=24)
        pygame.draw.rect(surf, chosen_color, panel, 4, border_radius=24)
        label = self.font_tiny.render("PLAYER COLOR", True, (164, 175, 204))
        surf.blit(label, (panel.left + 55, 202))
        for index, (name, color) in enumerate(PROFILE_COLORS.items()):
            rect = pygame.Rect(305 + index * 110, 245, 76, 76)
            selected = index == self.personalization_color_index
            pygame.draw.rect(surf, color, rect, border_radius=18)
            pygame.draw.rect(surf, WHITE if selected else (60, 66, 90), rect,
                             5 if selected else 2, border_radius=18)
            name_img = self.font_tiny.render(name, True, WHITE)
            surf.blit(name_img, name_img.get_rect(center=(rect.centerx, rect.bottom + 18)))

        toggles = (
            (pygame.Rect(330, 362, 380, 54), "SCREEN SHAKE", self.profile.screen_shake, "S"),
            (pygame.Rect(330, 430, 380, 54), "PLAYER TRAILS", self.profile.trails, "T"),
        )
        for rect, setting, enabled, key in toggles:
            pygame.draw.rect(surf, (28, 34, 59), rect, border_radius=14)
            pygame.draw.rect(surf, GREEN if enabled else RED, rect, 2, border_radius=14)
            text = self.font_small.render(f"{setting}   [{key}]", True, WHITE)
            surf.blit(text, (rect.left + 18, rect.centery - text.get_height() // 2))
            status = self.font_small.render("ON" if enabled else "OFF", True, GREEN if enabled else RED)
            surf.blit(status, status.get_rect(midright=(rect.right - 18, rect.centery)))

        finish = self.personalization_finish_rect()
        pygame.draw.rect(surf, chosen_color, finish, border_radius=17)
        pygame.draw.rect(surf, WHITE, finish, 3, border_radius=17)
        text = self.font_small.render("SAVE & ENTER CHATDASH  →", True, BLACK)
        surf.blit(text, text.get_rect(center=finish.center))

    def draw_global_reset(self, surf: pygame.Surface) -> None:
        rect = self.global_reset_rect()
        pygame.draw.rect(surf, (58, 20, 31), rect, border_radius=9)
        pygame.draw.rect(surf, RED, rect, 2, border_radius=9)
        label = self.font_tiny.render("RESET", True, WHITE)
        surf.blit(label, label.get_rect(center=rect.center))

        if not self.reset_confirm_open:
            return
        self.draw_dim_overlay(surf, 225)
        panel = pygame.Rect(WIDTH // 2 - 285, HEIGHT // 2 - 145, 570, 300)
        pygame.draw.rect(surf, (20, 20, 37), panel, border_radius=24)
        pygame.draw.rect(surf, RED, panel, 5, border_radius=24)
        heading = self.font_med.render("RESET ALL CHATDASH DATA?", True, RED)
        surf.blit(heading, heading.get_rect(center=(WIDTH // 2, panel.top + 54)))
        lines = (
            "This permanently deletes your name, personalization,",
            "level statistics, personal bests, and current attempt.",
            "ChatDash will return to first-time Sign In.",
        )
        for index, line in enumerate(lines):
            text = self.font_small.render(line, True, WHITE if index != 2 else YELLOW)
            surf.blit(text, text.get_rect(center=(WIDTH // 2, panel.top + 105 + index * 30)))
        confirm, cancel = self.reset_confirm_rects()
        pygame.draw.rect(surf, RED, confirm, border_radius=14)
        pygame.draw.rect(surf, WHITE, confirm, 2, border_radius=14)
        pygame.draw.rect(surf, (38, 48, 74), cancel, border_radius=14)
        pygame.draw.rect(surf, CYAN, cancel, 2, border_radius=14)
        delete_text = self.font_small.render("DELETE ALL", True, WHITE)
        cancel_text = self.font_small.render("CANCEL", True, WHITE)
        surf.blit(delete_text, delete_text.get_rect(center=confirm.center))
        surf.blit(cancel_text, cancel_text.get_rect(center=cancel.center))

    def draw_menu(self, surf: pygame.Surface) -> None:
        t = self.world_time
        title = self.font_big.render("CHATDASH", True, WHITE)
        shadow = self.font_big.render("CHATDASH", True, PINK)
        surf.blit(shadow, shadow.get_rect(center=(WIDTH // 2 + 4, 126 + 5)))
        surf.blit(title, title.get_rect(center=(WIDTH // 2, 126)))

        sub = self.font_small.render("8 forms • 8 escalating levels • adaptive music • interactive orbs", True, CYAN)
        surf.blit(sub, sub.get_rect(center=(WIDTH // 2, 180)))
        version = self.font_tiny.render(f"SOFTWARE v{VERSION}", True, (145, 158, 194))
        surf.blit(version, version.get_rect(center=(WIDTH // 2, 207)))

        # Press Start icon: glowing circular button with play triangle.
        center = (WIDTH // 2, 310)
        rad = int(74 + pulse(t, 5, -6, 8))
        draw_glow_circle(surf, center, rad, PINK, layers=5)
        pygame.draw.circle(surf, (20, 24, 45), center, rad)
        pygame.draw.circle(surf, WHITE, center, rad, 3)
        tri = [(center[0] + 30, center[1]), (center[0] - 20, center[1] - 34), (center[0] - 20, center[1] + 34)]
        pygame.draw.polygon(surf, YELLOW, tri)
        pygame.draw.polygon(surf, WHITE, tri, 3)

        press = self.font_med.render("PRESS START", True, WHITE)
        surf.blit(press, press.get_rect(center=(WIDTH // 2, 420)))
        hint = self.font_small.render("TAP or HOLD SPACE / UP / CLICK   •   P pause   •   R restart   •   M mute", True, (190, 200, 230))
        surf.blit(hint, hint.get_rect(center=(WIDTH // 2, 456)))

        # Decorative cube and UFO with streamer previews.
        self.draw_title_icons(surf)

    def draw_title_icons(self, surf: pygame.Surface) -> None:
        t = self.world_time
        # cube preview
        cx, cy = 210, 335
        trail = [(cx - i * 18, cy + math.sin(t * 6 - i) * 14 + ((-1) ** i) * 8) for i in range(1, 12)]
        pygame.draw.lines(surf, CYAN, False, trail + [(cx, cy)], 4)
        r = pygame.Rect(0, 0, 48, 48)
        r.center = (cx, cy)
        pygame.draw.rect(surf, BLUE, r, border_radius=7)
        pygame.draw.rect(surf, WHITE, r, 3, border_radius=7)
        pygame.draw.circle(surf, WHITE, (cx, cy), 4)

        # triangle UFO preview
        ux, uy = 820, 335
        trail2 = [(ux + i * 18, uy + math.sin(t * 6 + i) * 14 + ((-1) ** i) * 8) for i in range(1, 12)]
        pygame.draw.lines(surf, PINK, False, trail2 + [(ux, uy)], 4)
        pts = [(ux + 34, uy), (ux - 24, uy - 28), (ux - 22, uy + 30)]
        pygame.draw.polygon(surf, PURPLE, pts)
        pygame.draw.polygon(surf, WHITE, pts, 3)
        pygame.draw.circle(surf, WHITE, (ux, uy), 4)

    def draw_level_select(self, surf: pygame.Surface) -> None:
        selected = int(self.selected_level)
        title = self.font_big.render("CHOOSE A LEVEL", True, WHITE)
        surf.blit(title, title.get_rect(center=(WIDTH // 2, 88)))

        for index, card, active in self.level_select_cards():
            level = self.levels[index]
            width, height = card.size
            x, y = card.center
            if card.right < 0 or card.left > WIDTH:
                continue
            glow = pygame.Surface((width + 50, height + 50), pygame.SRCALPHA)
            pygame.draw.rect(glow, (*level.theme_b, 65 if active else 24),
                             (25, 25, width, height), border_radius=24)
            surf.blit(glow, (card.x - 25, card.y - 25))
            pygame.draw.rect(surf, (20, 24, 45), card, border_radius=20)
            pygame.draw.rect(surf, level.theme_b, card, 5 if active else 2, border_radius=20)

            number = self.font_big.render(str(index + 1), True, level.theme_a)
            surf.blit(number, number.get_rect(center=(x, card.top + (72 if active else 54))))
            name_font = self.font_small if active else self.font_tiny
            display_name = level.name.split("  ", 1)[-1]
            name = name_font.render(display_name, True, WHITE)
            surf.blit(name, name.get_rect(center=(x, card.top + (132 if active else 102))))

            if active:
                mode_count = len({event.target for event in level.events if event.kind == "portal"})
                info = self.font_tiny.render(
                    f"{int(level.bpm + index * 7)} BPM  •  {mode_count or 1} MODES", True, level.theme_a
                )
                surf.blit(info, info.get_rect(center=(x, card.top + 174)))
                for bar in range(8):
                    color = level.theme_b if bar <= index else (48, 53, 75)
                    pygame.draw.rect(surf, color, (card.left + 34 + bar * 24, card.top + 208, 17, 38), border_radius=5)

        left = [(20, 305), (60, 275), (60, 335)]
        right = [(WIDTH - 20, 305), (WIDTH - 60, 275), (WIDTH - 60, 335)]
        pygame.draw.polygon(surf, CYAN, left)
        pygame.draw.polygon(surf, CYAN, right)
        play_rect = pygame.Rect(WIDTH // 2 - 155, 480, 310, 58)
        pygame.draw.rect(surf, self.levels[selected].theme_b, play_rect, border_radius=18)
        pygame.draw.rect(surf, WHITE, play_rect, 3, border_radius=18)
        play = self.font_small.render(f"PLAY LEVEL {selected + 1}", True, BLACK)
        surf.blit(play, play.get_rect(center=play_rect.center))
        hint = self.font_tiny.render(
            "CLICK A CARD • ARROWS / 1–8 CHOOSE • ENTER START • ESC BACK", True, WHITE
        )
        surf.blit(hint, hint.get_rect(center=(WIDTH // 2, 558)))

    def draw_level_complete(self, surf: pygame.Surface) -> None:
        if self.state != LEVEL_COMPLETE:
            return
        # Banner drops down from above.
        t = 1 - clamp(self.complete_timer / 2.7, 0, 1)
        y = int(lerp(-120, 155, min(1, t * 2.2)))
        rect = pygame.Rect(130, y, WIDTH - 260, 120)
        glow = pygame.Surface((rect.w + 80, rect.h + 80), pygame.SRCALPHA)
        pygame.draw.rect(glow, (*self.level.theme_b, 70), (40, 40, rect.w, rect.h), border_radius=24)
        surf.blit(glow, (rect.x - 40, rect.y - 40), special_flags=pygame.BLEND_PREMULTIPLIED)
        pygame.draw.rect(surf, (22, 26, 48), rect, border_radius=22)
        pygame.draw.rect(surf, self.level.theme_b, rect, 5, border_radius=22)
        pygame.draw.rect(surf, WHITE, rect.inflate(-12, -12), 2, border_radius=18)

        text = self.font_big.render("LEVEL COMPLETE!", True, WHITE)
        surf.blit(text, text.get_rect(center=(WIDTH // 2, y + 48)))
        small = self.font_small.render("next level loading...", True, self.level.theme_a)
        surf.blit(small, small.get_rect(center=(WIDTH // 2, y + 92)))

    def draw_win(self, surf: pygame.Surface) -> None:
        title = self.font_big.render("YOU BEAT CHATDASH!", True, WHITE)
        surf.blit(title, title.get_rect(center=(WIDTH // 2, 180)))
        sub = self.font_med.render("All 8 levels cleared. Every form survived the neon machine.", True, YELLOW)
        surf.blit(sub, sub.get_rect(center=(WIDTH // 2, 245)))
        again = self.font_small.render("Click / Space to return to the start screen", True, CYAN)
        surf.blit(again, again.get_rect(center=(WIDTH // 2, 315)))

    def draw_pause(self, surf: pygame.Surface) -> None:
        if self.state != PAUSED:
            return
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 130))
        surf.blit(overlay, (0, 0))
        text = self.font_big.render("PAUSED", True, WHITE)
        surf.blit(text, text.get_rect(center=(WIDTH // 2, HEIGHT // 2 - 20)))
        hint = self.font_small.render("Press P to resume or R to restart", True, CYAN)
        surf.blit(hint, hint.get_rect(center=(WIDTH // 2, HEIGHT // 2 + 45)))

    def draw_death_summary(self, surf: pygame.Surface) -> None:
        if self.state != CRASHED or not self.death_summary:
            return
        data = self.death_summary
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill((2, 3, 10, 205))
        surf.blit(overlay, (0, 0))

        panel = pygame.Rect(88, 62, WIDTH - 176, HEIGHT - 118)
        glow = pygame.Surface((panel.w + 50, panel.h + 50), pygame.SRCALPHA)
        pygame.draw.rect(glow, (*RED, 60), (25, 25, panel.w, panel.h), border_radius=26)
        surf.blit(glow, (panel.x - 25, panel.y - 25))
        pygame.draw.rect(surf, (17, 20, 38), panel, border_radius=24)
        pygame.draw.rect(surf, RED, panel, 5, border_radius=24)
        pygame.draw.rect(surf, WHITE, panel.inflate(-14, -14), 2, border_radius=19)

        close = self.death_summary_close_rect()
        pygame.draw.rect(surf, RED, close, border_radius=13)
        pygame.draw.rect(surf, WHITE, close, 3, border_radius=13)
        pygame.draw.line(surf, WHITE, (close.left + 14, close.top + 14),
                         (close.right - 14, close.bottom - 14), 5)
        pygame.draw.line(surf, WHITE, (close.right - 14, close.top + 14),
                         (close.left + 14, close.bottom - 14), 5)

        title = self.font_big.render("ATTEMPT TERMINATED", True, RED)
        surf.blit(title, (panel.left + 32, panel.top + 22))
        level = self.font_med.render(str(data["level"]), True, self.level.theme_b)
        surf.blit(level, (panel.left + 36, panel.top + 91))
        cause = self.font_tiny.render(f'CAUSE // {data["cause"]}', True, RED)
        surf.blit(cause, (panel.left + 38, panel.top + 137))
        score = self.font_big.render(f'{int(data["score"]):,}', True, YELLOW)
        surf.blit(score, score.get_rect(topright=(panel.right - 38, panel.top + 98)))
        score_label = self.font_tiny.render("ATTEMPT SCORE", True, WHITE)
        surf.blit(score_label, score_label.get_rect(topright=(panel.right - 42, panel.top + 76)))

        pygame.draw.line(surf, (75, 82, 110), (panel.left + 30, panel.top + 165),
                         (panel.right - 30, panel.top + 165), 2)
        left_stats = (
            ("SECONDS SURVIVED", f'{float(data["survived"]):.2f}s'),
            ("LEVEL PROGRESS", f'{float(data["progress"]):.1f}%'),
            ("OBSTACLES DODGED", str(data["obstacles"])),
            ("ATTACKS DODGED", str(data["projectiles"])),
            ("STARS / ORBS", f'{data["stars"]} / {data["orbs"]}'),
        )
        right_stats = (
            ("FINAL MODE", str(data["mode"])),
            ("SECURITY ALERT", f'{float(data["alert"]):.0f}%'),
            ("LEVEL SPEED / MUSIC", f'{int(data["speed"])} / {int(data["bpm"])} BPM'),
            ("DEATHS ON LEVEL", str(data["deaths"])),
            ("BEST TIME / DODGES", f'{float(data["best_survival"]):.2f}s / {data["best_dodges"]}'),
        )
        for column, stats in enumerate((left_stats, right_stats)):
            x = panel.left + 42 + column * 410
            for row, (label_text, value_text) in enumerate(stats):
                y = panel.top + 190 + row * 49
                label = self.font_tiny.render(label_text, True, (155, 166, 196))
                value = self.font_small.render(value_text, True, WHITE)
                surf.blit(label, (x, y))
                surf.blit(value, (x + 205, y - 3))

        back = self.death_summary_back_rect()
        pygame.draw.rect(surf, (24, 92, 124), back, border_radius=13)
        pygame.draw.rect(surf, CYAN, back, 3, border_radius=13)
        back_text = self.font_small.render("←  BACK TO LEVELS", True, WHITE)
        surf.blit(back_text, back_text.get_rect(center=back.center))

        footer = self.font_tiny.render("X OR R: RESTART THIS LEVEL", True, CYAN)
        surf.blit(footer, footer.get_rect(center=(panel.right - 245, panel.bottom - 30)))

    def draw(self) -> None:
        base = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        self.draw_background(base)

        if self.state == SIGN_IN:
            self.draw_sign_in(base)
        elif self.state == INSTRUCTIONS:
            self.draw_instructions(base)
        elif self.state == PERSONALIZATION:
            self.draw_personalization(base)
        elif self.state == MENU:
            self.draw_menu(base)
        elif self.state == LEVEL_SELECT:
            self.draw_level_select(base)
        elif self.state == WIN:
            self.draw_win(base)
        else:
            # world objects
            for portal in self.portals:
                portal.draw(base, self.world_time)
            for orb in self.orbs:
                orb.draw(base, self.world_time)
            for star in self.stars_collectibles:
                star.draw(base, self.world_time)
            for obstacle in self.obstacles:
                obstacle.draw(base, self.world_time)
            for projectile in self.deterrence_projectiles:
                projectile.draw(base, self.world_time)
            for p in self.particles:
                p.draw(base)
            self.player.draw(base, self.profile_color, self.level.theme_b, self.world_time)
            for f in self.floaters:
                f.draw(base, self.font_small)
            self.draw_hud(base)
            self.draw_music_notes(base)
            self.draw_intruder_message(base)
            self.draw_level_complete(base)
            self.draw_pause(base)
            self.draw_death_summary(base)

        self.draw_global_reset(base)

        # screen shake
        offset = Vec2(0, 0)
        if (self.camera_shake > 0 and self.state != CRASHED
                and self.profile.screen_shake and not self.reset_confirm_open):
            offset.x = random.uniform(-self.camera_shake, self.camera_shake)
            offset.y = random.uniform(-self.camera_shake, self.camera_shake)
        self.screen.fill(BLACK)
        frame = base
        camera_triggers = (8.3, 16.1, 34.5, 40.4, 49.6, 55.5)
        camera_active = any(abs(self.level_time - trigger) < 1.05 for trigger in camera_triggers)
        if (self.level_index == 7 and self.state in (PLAYING, PAUSED)
                and camera_active and self.profile.screen_shake and not self.reset_confirm_open):
            # Mild camera rotation/zoom evokes Dash's trigger-heavy presentation
            # while keeping collision geometry readable and consistent.
            section = int(self.level_time // 6)
            angle = math.sin(self.world_time * (2.4 + section * 0.12)) * (2.0 + min(section, 5) * 0.65)
            zoom = 1.035 + 0.018 * pulse(self.world_time, 8)
            if 15.7 < self.level_time < 16.7 or 34.1 < self.level_time < 35.1:
                angle *= 2.2
                zoom += 0.035
            frame = pygame.transform.rotozoom(base, angle, zoom)
        target = frame.get_rect(center=(WIDTH // 2 + int(offset.x), HEIGHT // 2 + int(offset.y)))
        self.screen.blit(frame, target)
        pygame.display.flip()

    def run(self) -> None:
        while self.running:
            dt = self.clock.tick(FPS) / 1000.0
            dt = min(dt, 1 / 30)  # avoids huge jumps if the window is dragged
            for event in pygame.event.get():
                self.handle_event(event)
                if not self.running:
                    break
            if not self.running:
                break
            self.update(dt)
            self.draw()
        pygame.quit()


if __name__ == "__main__":
    ChatDashGame().run()
