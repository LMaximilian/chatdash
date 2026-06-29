"""
ChatDash - a polished mini Geometry-Dash-style game.

Install:
    pip install pygame

Run:
    python chatdash.py

Controls:
    SPACE / UP / Left Mouse  = jump or UFO flap
    P                         = pause
    R                         = restart current level after a crash
    M                         = mute / unmute sound
    ESC                       = quit
"""

from __future__ import annotations

from array import array
import math
import random
import sys
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

# Game states
MENU = "menu"
PLAYING = "playing"
PAUSED = "paused"
CRASHED = "crashed"
LEVEL_COMPLETE = "level_complete"
WIN = "win"


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
                "portal": self.make_tone(330, 0.20, 0.35, end_frequency=1050, wave="triangle"),
                "crash": self.make_noise(0.28, 0.42),
                "complete": self.make_chord((523, 659, 784), 0.42, 0.34),
                "win": self.make_chord((523, 659, 784, 1047), 0.75, 0.38),
                "pause": self.make_tone(300, 0.08, 0.22, end_frequency=220),
            }
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
            raw = (2 / math.pi) * math.asin(math.sin(phase)) if wave == "triangle" else (1.0 if math.sin(phase) >= 0 else -1.0)
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

    def play(self, name: str) -> None:
        if self.enabled and not self.muted and name in self.sounds:
            self.sounds[name].play()

    def toggle_mute(self) -> None:
        self.muted = not self.muted
        if self.muted and self.enabled:
            pygame.mixer.stop()


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
    add_spike_run(e, 4, 18, 2.15, ["single", "single", "double"], jitter=0.05)
    add_spike_run(e, 20, 38, 1.9, ["single", "double", "single", "single"], jitter=0.04)
    add_spike_run(e, 41, 57, 1.75, ["double", "single", "single"], jitter=0.03)
    levels.append(Level("1  CUBE COAST", 365, CYAN, BLUE, sorted(e, key=lambda x: x.t)))

    # Level 2: portals introduce UFO. Hazards remain gentle.
    e = []
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
    add_spike_run(e, 3.8, 13, 1.65, ["single", "double", "single"])
    e.append(Event(14.5, "portal", target="ufo"))
    add_burst(e, 18, [
        (0.0, "air_mid", "air"),
        (1.9, "air_low", "air"),
        (4.1, "air_high", "air"),
        (6.3, "air_mid", "air"),
        (8.6, "air_low", "air"),
    ])
    e.append(Event(30.5, "portal", target="cube"))
    add_spike_run(e, 34, 47, 1.55, ["single", "double", "single", "double"])
    e.append(Event(48.5, "portal", target="ufo"))
    add_burst(e, 52, [
        (0.0, "air_low", "air"),
        (2.0, "air_mid", "air"),
        (4.2, "air_high", "air"),
    ])
    levels.append(Level("3  SHARP SKY", 445, GREEN, CYAN, sorted(e, key=lambda x: x.t)))

    # Level 4: denser and more dramatic. Keeps large gaps around portal transitions.
    e = []
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

    return levels


def sanity_check_levels(levels: List[Level]) -> None:
    """Catch unfair obvious layout problems.

    This is not a perfect AI solver, but it prevents the design mistakes that
    usually make dash games impossible: hazards spaced too tightly, portals
    embedded inside hazards, or late hazards after the level should be over.
    """
    for idx, level in enumerate(levels, 1):
        last_hazard_t = -999.0
        last_portal_t = -999.0
        for ev in level.events:
            if ev.t >= LEVEL_LENGTH - 0.6:
                raise ValueError(f"Level {idx}: event too close to the 60s finish: {ev}")
            if ev.kind == "portal":
                if ev.t - last_hazard_t < 1.15:
                    raise ValueError(f"Level {idx}: portal too soon after hazard: {ev}")
                last_portal_t = ev.t
                continue

            # Hazards must not arrive too rapidly. Faster levels still need a fair rhythm.
            min_gap = 1.20 if level.speed < 480 else 1.15
            if ev.t - last_hazard_t < min_gap:
                raise ValueError(f"Level {idx}: hazards too close: {last_hazard_t:.2f} -> {ev.t:.2f}")
            if ev.t - last_portal_t < 1.60:
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

        # Glow underlay.
        for width, alpha in [(10, 30), (7, 45), (4, 90)]:
            glow = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            pygame.draw.lines(glow, (*color_a, alpha), False, sharp_points, width)
            surf.blit(glow, (0, 0), special_flags=pygame.BLEND_PREMULTIPLIED)

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

    def reset(self) -> None:
        self.mode = "cube"
        self.pos = Vec2(PLAYER_X, GROUND_Y - self.size / 2)
        self.vel = Vec2(0, 0)
        self.on_ground = True
        self.rotation = 0.0
        self.trail.clear()
        self.invuln = 0.0

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.vel.y = -240 if mode == "ufo" else 0
        if mode == "cube":
            self.pos.y = min(self.pos.y, GROUND_Y - self.size / 2)
        self.trail.clear()

    def rect(self) -> pygame.Rect:
        s = self.size
        if self.mode == "ufo":
            s = 42
        return pygame.Rect(int(self.pos.x - s / 2), int(self.pos.y - s / 2), s, s).inflate(-8, -8)

    def action(self) -> bool:
        if self.mode == "cube":
            if self.on_ground:
                self.vel.y = -790
                self.on_ground = False
                return True
        else:
            # UFO tap-flap. Strong but controlled.
            self.vel.y = -520
            self.on_ground = False
            return True
        return False

    def update(self, dt: float) -> None:
        self.invuln = max(0.0, self.invuln - dt)
        if self.mode == "cube":
            self.vel.y += 2300 * dt
            self.pos.y += self.vel.y * dt
            floor_y = GROUND_Y - self.size / 2
            if self.pos.y >= floor_y:
                self.pos.y = floor_y
                self.vel.y = 0
                self.on_ground = True
                # Snap rotation to square-ish angles for polish.
                self.rotation = round(self.rotation / 90) * 90
            else:
                self.rotation += 430 * dt
        else:
            self.vel.y += 1450 * dt
            self.vel.y = clamp(self.vel.y, -650, 650)
            self.pos.y += self.vel.y * dt
            # Keep UFO inside screen. Touching floor/ceiling is allowed but bouncy.
            top = 72
            bottom = GROUND_Y - 42
            if self.pos.y < top:
                self.pos.y = top
                self.vel.y = 90
            if self.pos.y > bottom:
                self.pos.y = bottom
                self.vel.y = -80
            self.rotation = clamp(self.vel.y * 0.08, -35, 35)

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

    def draw(self, surf: pygame.Surface, color_a: Color, color_b: Color, time_s: float) -> None:
        self.trail.draw(surf, color_b, color_a, time_s)
        if self.invuln > 0 and int(self.invuln * 18) % 2 == 0:
            return
        if self.mode == "cube":
            self.draw_cube(surf, color_a, color_b)
        else:
            self.draw_ufo(surf, color_a, color_b)


class Obstacle:
    def __init__(self, kind: str, x: float, speed: float, theme: Color):
        self.kind = kind
        self.x = x
        self.speed = speed
        self.theme = theme
        self.dead = False
        self.width = {"single": 38, "double": 78}.get(kind, 46)

    def update(self, dt: float) -> bool:
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
        elif self.kind.startswith("air"):
            y_map = {"air_low": 410, "air_mid": 315, "air_high": 220}
            y = y_map[self.kind]
            r = 28
            # Sharp floating triangle shard.
            polys.append([(self.x + r, y), (self.x - r, y - r * 0.9), (self.x - r * 0.72, y + r * 0.95)])
        return polys

    def collides(self, rect: pygame.Rect) -> bool:
        for poly in self.spike_polys():
            if rect_touches_poly_rough(rect, poly, shrink=12):
                return True
        return False

    def draw(self, surf: pygame.Surface, time_s: float) -> None:
        for poly in self.spike_polys():
            # Glow
            p_rect = polygon_rect(poly).inflate(24, 24)
            glow = pygame.Surface((p_rect.w, p_rect.h), pygame.SRCALPHA)
            moved = [(x - p_rect.x, y - p_rect.y) for x, y in poly]
            pygame.draw.polygon(glow, (*self.theme, 45), moved)
            surf.blit(glow, (p_rect.x, p_rect.y), special_flags=pygame.BLEND_PREMULTIPLIED)

            pygame.draw.polygon(surf, self.theme, poly)
            pygame.draw.polygon(surf, WHITE, poly, 2)

            # Inner shine line.
            cx = sum(x for x, _ in poly) / 3
            cy = sum(y for _, y in poly) / 3
            tip = min(poly, key=lambda p: p[1]) if self.kind in ("single", "double") else max(poly, key=lambda p: p[0])
            pygame.draw.line(surf, (255, 255, 255), (int(cx), int(cy)), (int(tip[0]), int(tip[1])), 1)


class Portal:
    def __init__(self, target: str, x: float, speed: float, theme: Color):
        self.target = target
        self.x = x
        self.y = 310 if target == "ufo" else GROUND_Y - 70
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
        return Vec2(self.x, self.y).distance_to(player.pos) < self.radius + 30

    def draw(self, surf: pygame.Surface, time_s: float) -> None:
        wobble = int(5 * pulse(time_s, 6, -1, 1))
        center = (int(self.x), int(self.y))
        color = PURPLE if self.target == "ufo" else CYAN
        draw_glow_circle(surf, center, self.radius + wobble, color, layers=4)
        pygame.draw.circle(surf, WHITE, center, self.radius + wobble, 2)

        # Symbol inside: triangle for UFO target, square for cube target.
        if self.target == "ufo":
            pts = [(self.x + 16, self.y), (self.x - 12, self.y - 16), (self.x - 12, self.y + 16)]
            pygame.draw.polygon(surf, color, pts)
            pygame.draw.polygon(surf, WHITE, pts, 2)
        else:
            r = pygame.Rect(0, 0, 28, 28)
            r.center = center
            pygame.draw.rect(surf, color, r, border_radius=5)
            pygame.draw.rect(surf, WHITE, r, 2, border_radius=5)


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
    def __init__(self):
        pygame.mixer.pre_init(44100, -16, 1, 512)
        pygame.init()
        pygame.display.set_caption("ChatDash - Cube, Spikes, Portals, UFO-ish Triangles")
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        self.clock = pygame.time.Clock()
        self.font_big = pygame.font.SysFont("arialblack", 56)
        self.font_med = pygame.font.SysFont("arialblack", 30)
        self.font_small = pygame.font.SysFont("arial", 20, bold=True)
        self.font_tiny = pygame.font.SysFont("arial", 16, bold=True)
        self.sound = SoundManager()

        self.levels = build_levels()
        sanity_check_levels(self.levels)

        self.player = Player()
        self.level_index = 0
        self.level_time = 0.0
        self.world_time = 0.0
        self.state = MENU
        self.prev_state = MENU
        self.spawn_cursor = 0
        self.obstacles: List[Obstacle] = []
        self.portals: List[Portal] = []
        self.particles: List[Particle] = []
        self.floaters: List[FloatingText] = []
        self.camera_shake = 0.0
        self.complete_timer = 0.0
        self.crash_timer = 0.0
        self.stars = self.make_stars()
        self.best_level = 0

    def make_stars(self) -> List[Tuple[float, float, float, float]]:
        random.seed(7)
        stars = []
        for _ in range(95):
            x = random.uniform(0, WIDTH)
            y = random.uniform(20, GROUND_Y - 70)
            r = random.uniform(1, 3)
            spd = random.uniform(10, 46)
            stars.append((x, y, r, spd))
        return stars

    @property
    def level(self) -> Level:
        return self.levels[self.level_index]

    def reset_level(self) -> None:
        self.level_time = 0.0
        self.spawn_cursor = 0
        self.obstacles.clear()
        self.portals.clear()
        self.particles.clear()
        self.floaters.clear()
        self.camera_shake = 0.0
        self.crash_timer = 0.0
        self.complete_timer = 0.0
        self.player.reset()
        self.state = PLAYING

    def start_game(self) -> None:
        self.level_index = 0
        self.best_level = 0
        self.reset_level()
        self.sound.play("start")

    def emit_burst(self, pos: Vec2, color: Color, amount: int = 28, power: float = 260) -> None:
        for _ in range(amount):
            a = random.uniform(0, math.tau)
            s = random.uniform(60, power)
            vel = Vec2(math.cos(a) * s, math.sin(a) * s)
            self.particles.append(Particle(pos, vel, color, random.uniform(0.4, 0.9), random.uniform(2, 6)))

    def crash(self) -> None:
        self.state = CRASHED
        self.crash_timer = 0.95
        self.camera_shake = 18
        self.emit_burst(self.player.pos, RED, amount=44, power=430)
        self.floaters.append(FloatingText("BONK!  Press R or wait...", (WIDTH // 2, 150), RED))
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
            self.reset_level()

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.QUIT:
            pygame.quit()
            sys.exit()

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                pygame.quit()
                sys.exit()
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
                if self.state == MENU:
                    self.start_game()
                elif self.state == PLAYING:
                    if self.player.action():
                        self.sound.play("jump" if self.player.mode == "cube" else "flap")
                elif self.state == WIN:
                    self.state = MENU
                elif self.state == LEVEL_COMPLETE and self.complete_timer < 1.25:
                    self.next_level()

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.state == MENU:
                self.start_game()
            elif self.state == PLAYING:
                if self.player.action():
                    self.sound.play("jump" if self.player.mode == "cube" else "flap")
            elif self.state == WIN:
                self.state = MENU
            elif self.state == LEVEL_COMPLETE and self.complete_timer < 1.25:
                self.next_level()

    def spawn_events(self) -> None:
        events = self.level.events
        while self.spawn_cursor < len(events) and events[self.spawn_cursor].t <= self.level_time:
            ev = events[self.spawn_cursor]
            if ev.kind == "portal":
                self.portals.append(Portal(ev.target or "ufo", WIDTH + 70, self.level.speed, self.level.theme_b))
            else:
                self.obstacles.append(Obstacle(ev.kind, WIDTH + 60, self.level.speed, self.level.theme_b))
            self.spawn_cursor += 1

    def update_playing(self, dt: float) -> None:
        self.level_time += dt
        self.world_time += dt
        self.spawn_events()

        self.player.update(dt)
        self.obstacles = [o for o in self.obstacles if o.update(dt)]
        self.portals = [p for p in self.portals if p.update(dt)]
        self.particles = [p for p in self.particles if p.update(dt)]
        self.floaters = [f for f in self.floaters if f.update(dt)]
        self.camera_shake = max(0.0, self.camera_shake - 32 * dt)

        # Portal use.
        for portal in self.portals:
            if not portal.used and portal.touches_player(self.player):
                portal.used = True
                portal.dead = True
                self.player.set_mode(portal.target)
                self.sound.play("portal")
                self.player.invuln = 0.25
                self.emit_burst(Vec2(portal.x, portal.y), PURPLE if portal.target == "ufo" else CYAN, amount=38, power=300)
                label = "TRIANGLE UFO MODE" if portal.target == "ufo" else "CUBE MODE"
                self.floaters.append(FloatingText(label, (WIDTH // 2, 110), PURPLE if portal.target == "ufo" else CYAN))

        self.portals = [p for p in self.portals if not p.dead]

        # Collision.
        hit_rect = self.player.rect()
        if self.player.invuln <= 0:
            for obstacle in self.obstacles:
                if obstacle.collides(hit_rect):
                    self.crash()
                    break

        if self.level_time >= LEVEL_LENGTH:
            self.finish_level()

    def update(self, dt: float) -> None:
        self.world_time += dt if self.state != PAUSED else 0
        if self.state == PLAYING:
            self.update_playing(dt)
        elif self.state == CRASHED:
            self.crash_timer -= dt
            self.particles = [p for p in self.particles if p.update(dt)]
            self.floaters = [f for f in self.floaters if f.update(dt)]
            self.camera_shake = max(0.0, self.camera_shake - 40 * dt)
            if self.crash_timer <= 0:
                self.reset_level()
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
        lvl = self.level if self.state not in (MENU, WIN) else self.levels[min(self.level_index, len(self.levels) - 1)]
        # vertical gradient
        for y in range(HEIGHT):
            t = y / HEIGHT
            r = int(lerp(8, 20, t))
            g = int(lerp(10, 18, t))
            b = int(lerp(27, 42, t))
            pygame.draw.line(surf, (r, g, b), (0, y), (WIDTH, y))

        # stars / streaks
        for i, (x, y, r, spd) in enumerate(self.stars):
            xx = (x - self.world_time * spd) % (WIDTH + 40) - 20
            tw = pulse(self.world_time + i, 2.3, 0.35, 1.0)
            col = tuple(int(lerp(80, lvl.theme_a[j], tw)) for j in range(3))
            pygame.draw.circle(surf, col, (int(xx), int(y)), int(r))
            if spd > 35:
                pygame.draw.line(surf, col, (int(xx), int(y)), (int(xx + 18), int(y)), 1)

        # moving grid
        grid_color = (*lvl.theme_a, 35)
        grid = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        offset = int((self.world_time * lvl.speed * 0.33) % 48)
        for x in range(-offset, WIDTH, 48):
            pygame.draw.line(grid, grid_color, (x, 0), (x, GROUND_Y), 1)
        for y in range(80, GROUND_Y, 48):
            pygame.draw.line(grid, grid_color, (0, y), (WIDTH, y), 1)
        surf.blit(grid, (0, 0))

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

        mode_text = "CUBE: SPACE = JUMP" if self.player.mode == "cube" else "TRIANGLE UFO: TAP = FLAP"
        mode_img = self.font_tiny.render(mode_text, True, lvl.theme_a)
        surf.blit(mode_img, (22, 48))

    def draw_menu(self, surf: pygame.Surface) -> None:
        t = self.world_time
        title = self.font_big.render("CHATDASH", True, WHITE)
        shadow = self.font_big.render("CHATDASH", True, PINK)
        surf.blit(shadow, shadow.get_rect(center=(WIDTH // 2 + 4, 126 + 5)))
        surf.blit(title, title.get_rect(center=(WIDTH // 2, 126)))

        sub = self.font_small.render("cube jumps, portals pop, sharp triangle UFO goes NYOOM", True, CYAN)
        surf.blit(sub, sub.get_rect(center=(WIDTH // 2, 180)))

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
        hint = self.font_small.render("SPACE / UP / CLICK   •   P pause   •   R restart   •   M mute", True, (190, 200, 230))
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
        sub = self.font_med.render("All 5 levels cleared. The triangle UFO has been promoted to Very Pointy Aircraft.", True, YELLOW)
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

    def draw(self) -> None:
        base = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        self.draw_background(base)

        if self.state == MENU:
            self.draw_menu(base)
        elif self.state == WIN:
            self.draw_win(base)
        else:
            # world objects
            for portal in self.portals:
                portal.draw(base, self.world_time)
            for obstacle in self.obstacles:
                obstacle.draw(base, self.world_time)
            for p in self.particles:
                p.draw(base)
            self.player.draw(base, self.level.theme_a, self.level.theme_b, self.world_time)
            for f in self.floaters:
                f.draw(base, self.font_small)
            self.draw_hud(base)
            self.draw_level_complete(base)
            self.draw_pause(base)

        # screen shake
        offset = Vec2(0, 0)
        if self.camera_shake > 0:
            offset.x = random.uniform(-self.camera_shake, self.camera_shake)
            offset.y = random.uniform(-self.camera_shake, self.camera_shake)
        self.screen.fill(BLACK)
        self.screen.blit(base, (int(offset.x), int(offset.y)))
        pygame.display.flip()

    def run(self) -> None:
        while True:
            dt = self.clock.tick(FPS) / 1000.0
            dt = min(dt, 1 / 30)  # avoids huge jumps if the window is dragged
            for event in pygame.event.get():
                self.handle_event(event)
            self.update(dt)
            self.draw()


if __name__ == "__main__":
    ChatDashGame().run()
