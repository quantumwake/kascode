"""
QuantumWakE Starfield v2 — Interactive 3D starfield with cooler effects.

Effects included:
  • Nebula clouds (semi-transparent colored gas)
  • Spiral galaxy arms (stars arranged in logarithmic spirals)
  • Star trails (fade history for motion blur)
  • Bloom / glow on bright/close stars
  • Twinkling (sinusoidal brightness oscillation)
  • Shooting stars (random fast meteors with trails)
  • Color-shifting over time
  • Dust particles for depth
  • Central galaxy core glow
  • Optional warp-speed mode (press W)
  • Keyboard controls: W=warp, S=speed, R=reset, Q=quit
"""

import random
import math
import os
import sys
import time

# ─── Configuration ───────────────────────────────────────────────
SCREEN_W, SCREEN_H = 1200, 1000
NUM_STARS = 800
NUM_GALAXY_STARS = 300       # arranged in spiral arms
NUM_DUST = 200
NUM_SHOOTING = 4
NUM_NEBULAE = 6
STAR_DEPTH = 3000
FOCAL_LENGTH = 600
OUTPUT_GIF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "starfield_v2.gif")
DURATION_SECONDS = 20
FPS = 30

# Galaxy color palette
NEBULA_COLORS = [
    (60, 20, 100),   # deep purple
    (20, 40, 90),    # deep blue
    (80, 15, 60),    # magenta
    (15, 60, 80),    # teal
    (100, 30, 50),   # crimson
]

STAR_PALETTE = [
    (255, 255, 255),   # white dwarf
    (173, 216, 255),   # blue giant
    (255, 223, 148),   # yellow sun
    (255, 140, 100),   # orange red giant
    (255, 80, 80),     # red giant
    (180, 130, 255),   # violet
    (100, 255, 200),   # cyan exotic
]

GALAXY_COLORS = [
    (180, 160, 220),   # pale violet
    (120, 160, 220),   # pale blue
    (220, 180, 140),   # warm gold
    (255, 255, 255),   # core white
]

TWINKLE_SPEEDS = [0.02, 0.04, 0.07, 0.12, 0.2]
MAX_TRAIL = 6


# ─── Helpers ─────────────────────────────────────────────────────
def lerp(a, b, t):
    return a + (b - a) * t


def clamp(v, lo=0, hi=255):
    return max(lo, min(hi, v))


def project_3d(x, y, z):
    if z < 1:
        return None
    scale = FOCAL_LENGTH / z
    sx = SCREEN_W // 2 + int(x * scale)
    sy = SCREEN_H // 2 + int(y * scale)
    radius = max(1, min(8, int(400.0 / z)))
    brightness = min(1.0, 600.0 / z)
    return sx, sy, radius, brightness


# ─── Star classes ────────────────────────────────────────────────
class Star:
    """Standard star with twinkling, color-shift, and trail."""
    __slots__ = (
        'x', 'y', 'z', 'base_color', 'speed',
        'twinkle_phase', 'twinkle_speed', 'hue_offset', 'trail',
    )

    def __init__(self, x=None, y=None, z=None):
        self.x = random.uniform(-700, 700)
        self.y = random.uniform(-550, 550)
        self.z = random.uniform(10, STAR_DEPTH)
        self.base_color = random.choice(STAR_PALETTE)
        self.speed = random.uniform(1.5, 6.0)
        self.twinkle_phase = random.uniform(0, math.tau)
        self.twinkle_speed = random.choice(TWINKLE_SPEEDS)
        self.hue_offset = random.uniform(-0.15, 0.15)  # color shift range
        self.trail = []  # list of (sx, sy, r, brightness, r, g, b)

    def reset(self):
        self.x = random.uniform(-700, 700)
        self.y = random.uniform(-550, 550)
        self.z = random.uniform(10, STAR_DEPTH)
        self.base_color = random.choice(STAR_PALETTE)
        self.speed = random.uniform(1.5, 6.0)
        self.twinkle_phase = random.uniform(0, math.tau)
        self.trail = []

    def move(self, warp=False):
        factor = 4.0 if warp else 1.0
        self.z -= self.speed * factor
        self.twinkle_phase += self.twinkle_speed
        if self.z <= 1:
            self.reset()

    def color_at(self, time):
        r, g, b = self.base_color
        shift = self.hue_offset * math.sin(time * 0.3 + self.twinkle_phase)
        r = clamp(int(r + shift * 80))
        g = clamp(int(g + shift * 40))
        b = clamp(int(b - shift * 60))
        return r, g, b

    def get(self, time, warp=False):
        self.move(warp)
        proj = project_3d(self.x, self.y, self.z)
        if proj is None:
            self.trail = []
            return None
        sx, sy, radius, brightness = proj
        r, g, b = self.color_at(time)
        # Twinkle
        twinkle = 0.6 + 0.4 * math.sin(self.twinkle_phase)
        r = clamp(int(r * brightness * twinkle))
        g = clamp(int(g * brightness * twinkle))
        b = clamp(int(b * brightness * twinkle))
        entry = (sx, sy, radius, brightness, r, g, b)
        self.trail.append(entry)
        if len(self.trail) > MAX_TRAIL:
            self.trail.pop(0)
        return entry


class GalaxyStar:
    """Star belonging to a spiral galaxy arm."""
    __slots__ = ('x', 'y', 'z', 'color', 'speed', 'twinkle_phase', 'trail')

    def __init__(self, arm, angle, dist_from_center):
        self.x = 0
        self.y = 0
        self.z = 0
        self.color = random.choice(GALAXY_COLORS)
        self.speed = random.uniform(1.0, 4.0)
        self.twinkle_phase = random.uniform(0, math.tau)
        self.trail = []
        self._place_on_arm(arm, angle, dist_from_center)

    def _place_on_arm(self, arm, angle, dist_from_center):
        # Logarithmic spiral: r = a * e^(b*theta)
        # We map angle to a spiral position
        a = 200.0
        b = 0.15
        r = a * math.exp(b * (angle / 50.0))
        # Add some scatter
        scatter = dist_from_center * 30.0
        offset_x = random.gauss(0, scatter)
        offset_y = random.gauss(0, scatter)
        self.x = r * math.cos(angle) + offset_x
        self.y = r * math.sin(angle) + offset_y
        self.z = random.uniform(10, STAR_DEPTH)

    def reset(self):
        arm = random.randint(0, 4)
        angle = random.uniform(0, math.tau * 2.0)
        dist = random.uniform(0, 1.0)
        self._place_on_arm(arm, angle, dist)
        self.z = random.uniform(10, STAR_DEPTH)
        self.trail = []

    def move(self, warp=False):
        factor = 3.0 if warp else 1.0
        self.z -= self.speed * factor
        if self.z <= 1:
            self.reset()

    def get(self, time, warp=False):
        self.move(warp)
        proj = project_3d(self.x, self.y, self.z)
        if proj is None:
            self.trail = []
            return None
        sx, sy, radius, brightness = proj
        r, g, b = self.color
        twinkle = 0.7 + 0.3 * math.sin(self.twinkle_phase + time * 0.5)
        r = clamp(int(r * brightness * twinkle))
        g = clamp(int(g * brightness * twinkle))
        b = clamp(int(b * brightness * twinkle))
        entry = (sx, sy, radius, brightness, r, g, b)
        self.trail.append(entry)
        if len(self.trail) > MAX_TRAIL:
            self.trail.pop(0)
        return entry


class ShootingStar:
    """Fast meteor with a trailing tail."""
    __slots__ = ('x', 'y', 'z', 'vx', 'vy', 'vz', 'color', 'trail', 'active', 'life')

    def __init__(self):
        self.reset()

    def reset(self):
        # Start far away, aim toward screen
        self.x = random.uniform(-800, 800)
        self.y = random.uniform(-600, 600)
        self.z = random.uniform(500, STAR_DEPTH)
        # Velocity toward center-ish
        cx, cy = 0, 0  # aim near center
        dx = cx - self.x
        dy = cy - self.y
        dist = math.sqrt(dx * dx + dy * dy)
        speed = random.uniform(15, 30)
        self.vx = (dx / dist) * speed + random.uniform(-3, 3)
        self.vy = (dy / dist) * speed + random.uniform(-3, 3)
        self.vz = -random.uniform(10, 25)
        self.color = random.choice([(255, 255, 255), (200, 220, 255), (255, 200, 180)])
        self.trail = []
        self.active = True
        self.life = random.uniform(30, 80)  # frames

    def move(self):
        self.x += self.vx
        self.y += self.vy
        self.z += self.vz
        self.life -= 1
        if self.life <= 0 or self.z <= 1:
            self.reset()

    def get(self):
        self.move()
        proj = project_3d(self.x, self.y, self.z)
        if proj is None:
            self.trail = []
            return None
        sx, sy, radius, brightness = proj
        alpha = min(1.0, self.life / 20.0)  # fade in
        r, g, b = self.color
        r = clamp(int(r * brightness * alpha))
        g = clamp(int(g * brightness * alpha))
        b = clamp(int(b * brightness * alpha))
        entry = (sx, sy, max(2, radius * 2), brightness * alpha, r, g, b)
        self.trail.append(entry)
        if len(self.trail) > 10:
            self.trail.pop(0)
        return entry


class NebulaCloud:
    """Semi-transparent colored gas cloud in the background."""
    __slots__ = ('cx', 'cy', 'radius', 'color', 'opacity')

    def __init__(self):
        self.cx = random.uniform(-400, 400)
        self.cy = random.uniform(-300, 300)
        self.radius = random.uniform(100, 300)
        self.color = random.choice(NEBULA_COLORS)
        self.opacity = random.uniform(0.03, 0.08)
        self.drift = random.uniform(0.05, 0.2)
        self.phase = random.uniform(0, math.tau)

    def update(self, time):
        self.cx += self.drift * math.sin(time * 0.1 + self.phase)
        self.cy += self.drift * math.cos(time * 0.08 + self.phase) * 0.5


class DustParticle:
    """Tiny floating particles for depth."""
    __slots__ = ('x', 'y', 'z', 'speed')

    def __init__(self):
        self.reset()

    def reset(self):
        self.x = random.uniform(-600, 600)
        self.y = random.uniform(-400, 400)
        self.z = random.uniform(50, STAR_DEPTH * 0.7)
        self.speed = random.uniform(0.5, 2.0)

    def move(self, warp=False):
        factor = 3.0 if warp else 1.0
        self.z -= self.speed * factor
        if self.z <= 5:
            self.reset()


# ─── Drawing helpers ─────────────────────────────────────────────
def draw_glow(screen, sx, sy, radius, r, g, b):
    """Draw a soft glow around bright stars (bloom effect)."""
    if radius < 2:
        return
    glow_radius = radius * 4
    if glow_radius > 40:
        glow_radius = 40
    # Outer glow (large, very transparent)
    for gr in range(glow_radius, 0, -3):
        a = 1.0 - (gr / glow_radius)
        alpha = int(a * 40)  # very subtle
        if alpha < 2:
            continue
        # Use a semi-transparent surface for blending
        sg = pygame.Surface((gr * 2 + 1, gr * 2 + 1), pygame.SRCALPHA)
        gray = (r, g, b, alpha)
        pygame.draw.circle(sg, gray, (gr, gr), gr)
        screen.blit(sg, (sx - gr, sy - gr))
    # Core
    pygame.draw.circle(screen, (r, g, b), (sx, sy), radius)


def draw_stars_on_surface(surface, stars, time, warp=False, galaxy_stars=None):
    """Render all star elements onto a pygame Surface."""
    if galaxy_stars is None:
        galaxy_stars = []

    # 1) Draw nebula clouds (background layer)
    for nebula in NebulaCloud.__dict__.get('__slots__', []):
        pass  # handled by caller

    # 2) Draw galaxy core glow (central bright spot)
    core_x, core_y = SCREEN_W // 2, SCREEN_H // 2
    core_radius = 25
    for gr in range(core_radius, 0, -2):
        a = 1.0 - (gr / core_radius)
        alpha = int(a * 25)
        if alpha < 2:
            continue
        sg = pygame.Surface((gr * 2 + 1, gr * 2 + 1), pygame.SRCALPHA)
        pygame.draw.circle(sg, (180, 160, 220, alpha), (gr, gr), gr)
        surface.blit(sg, (core_x - gr, core_y - gr))
    pygame.draw.circle(surface, (255, 255, 255), (core_x, core_y), 5)

    # 3) Draw dust (tiny faint dots)
    for dust in _dust_particles:
        proj = project_3d(dust.x, dust.y, dust.z)
        if proj is None:
            continue
        sx, sy, radius, brightness = proj
        if 0 <= sx < SCREEN_W and 0 <= sy < SCREEN_H:
            v = int(60 * brightness)
            surface.set_at((sx, sy), (v, v, v + 20))

    # 4) Draw galaxy stars (sorted by z for depth)
    galaxy_entries = []
    for gs in galaxy_stars:
        entry = gs.get(time, warp)
        if entry is None:
            continue
        sx, sy, radius, brightness, r, g, b = entry
        if not (0 <= sx < SCREEN_W and 0 <= sy < SCREEN_H):
            continue
        galaxy_entries.append((gs.z, sx, sy, radius, r, g, b, gs.trail))

    galaxy_entries.sort(key=lambda e: e[0])  # far to near

    for gz, sx, sy, radius, r, g, b, trail in galaxy_entries:
        # Draw trail (faint ghosting)
        for i, (tsx, tsy, tr, tb, tr2, tg, tb2) in enumerate(trail):
            alpha = (i / max(1, len(trail))) ** 2
            rv = clamp(int(tr2 * alpha))
            gv = clamp(int(tg * alpha))
            bv = clamp(int(tb2 * alpha))
            r_tr = max(1, max(1, int(tr * 0.5)))
            pygame.draw.circle(surface, (rv, gv, bv), (tsx, tsy), r_tr)
        # Draw core
        if radius >= 3:
            draw_glow(surface, sx, sy, radius, r, g, b)
        else:
            pygame.draw.circle(surface, (r, g, b), (sx, sy), radius)

    # 5) Draw regular stars (sorted by z)
    star_entries = []
    for star in stars:
        entry = star.get(time, warp)
        if entry is None:
            continue
        sx, sy, radius, brightness, r, g, b = entry
        if not (0 <= sx < SCREEN_W and 0 <= sy < SCREEN_H):
            continue
        star_entries.append((star.z, sx, sy, radius, r, g, b, star.trail))

    star_entries.sort(key=lambda e: e[0])

    for sz, sx, sy, radius, r, g, b, trail in star_entries:
        # Draw trail
        for i, (tsx, tsy, tr, tb, tr2, tg, tb2) in enumerate(trail):
            alpha = (i / max(1, len(trail))) ** 2
            rv = clamp(int(tr2 * alpha))
            gv = clamp(int(tg * alpha))
            bv = clamp(int(tb2 * alpha))
            r_tr = max(1, max(1, int(tr * 0.5)))
            pygame.draw.circle(surface, (rv, gv, bv), (tsx, tsy), r_tr)
        # Draw core
        if radius >= 3:
            draw_glow(surface, sx, sy, radius, r, g, b)
        else:
            pygame.draw.circle(surface, (r, g, b), (sx, sy), radius)

    # 6) Draw shooting stars (on top)
    for ss in shooting_stars:
        entry = ss.get()
        if entry is None:
            continue
        sx, sy, radius, brightness, r, g, b = entry
        if not (0 <= sx < SCREEN_W and 0 <= sy < SCREEN_H):
            continue
        # Draw trail (longer for shooting stars)
        for i, (tsx, tsy, tr, tb, tr2, tg, tb2) in enumerate(ss.trail):
            alpha = (i / max(1, len(ss.trail))) ** 1.5
            rv = clamp(int(tr2 * alpha))
            gv = clamp(int(tg * alpha))
            bv = clamp(int(tb2 * alpha))
            r_tr = max(1, int(tr * 0.4))
            pygame.draw.circle(surface, (rv, gv, bv), (tsx, tsy), r_tr)
        # Bright head
        pygame.draw.circle(surface, (r, g, b), (sx, sy), max(2, radius))


# ─── Main ────────────────────────────────────────────────────────
stars = []
galaxy_stars = []
shooting_stars = []
nebula_clouds = []
_dust_particles = []

# Create regular stars
for _ in range(NUM_STARS):
    stars.append(Star())

# Create galaxy stars (arranged in spiral arms)
for arm in range(5):  # 5 spiral arms
    for _ in range(NUM_GALAXY_STARS // 5):
        angle = random.uniform(arm * math.tau / 5, (arm + 1) * math.tau / 5)
        dist = random.uniform(0, 1.0)
        galaxy_stars.append(GalaxyStar(arm, angle, dist))

# Create shooting stars
for _ in range(NUM_SHOOTING):
    shooting_stars.append(ShootingStar())

# Create nebula clouds
for _ in range(NUM_NEBULAE):
    nebula_clouds.append(NebulaCloud())

# Create dust particles
for _ in range(NUM_DUST):
    _dust_particles.append(DustParticle())


# ─── Try live mode with Pygame ──────────────────────────────────
try:
    import pygame
    pygame.init()

    # Create an offscreen surface for compositing (avoids SDL surface issues)
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
    pygame.display.set_caption("QuantumWakE Starfield v2 — Press W=warp, S=speed, R=reset, Q=quit")
    clock = pygame.time.Clock()
    running = True
    warp_mode = False
    speed_mult = 1.0
    start_time = time.time()

    print("Starfield v2 running — press W=warp, S=speed, R=reset, Q=quit, or close window.")

    while running:
        elapsed = time.time() - start_time

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_q:
                    running = False
                elif event.key == pygame.K_w:
                    warp_mode = not warp_mode
                    print(f"Warp drive: {'ON' if warp_mode else 'OFF'}")
                elif event.key == pygame.K_s:
                    speed_mult = round(speed_mult * 1.5, 1)
                    print(f"Speed multiplier: {speed_mult}x")
                elif event.key == pygame.K_r:
                    for s in stars:
                        s.reset()
                    for gs in galaxy_stars:
                        gs.reset()
                    for ss in shooting_stars:
                        ss.reset()
                    for dc in nebula_clouds:
                        dc.__init__()
                    for dp in _dust_particles:
                        dp.reset()
                    print("Reset!")

        screen.fill((5, 5, 25))  # deep space background

        # Update nebula clouds
        for nc in nebula_clouds:
            nc.update(elapsed)

        # Draw everything onto screen
        draw_stars_on_surface(screen, stars, elapsed, warp_mode, galaxy_stars)

        # Draw nebula clouds (semi-transparent overlay)
        for nc in nebula_clouds:
            cx = SCREEN_W // 2 + int(nc.cx)
            cy = SCREEN_H // 2 + int(nc.cy)
            r = int(nc.radius)
            # Draw as a radial gradient circle
            for gr in range(r, 0, -4):
                a = int(nc.opacity * (1.0 - gr / r) * 255)
                if a < 3:
                    continue
                sg = pygame.Surface((gr * 2 + 1, gr * 2 + 1), pygame.SRCALPHA)
                nr = clamp(nc.color[0])
                ng = clamp(nc.color[1])
                nb = clamp(nc.color[2])
                pygame.draw.circle(sg, (nr, ng, nb, a), (gr, gr), gr)
                screen.blit(sg, (cx - gr, cy - gr))

        # Warp mode visual: radial streak lines
        if warp_mode:
            for _ in range(30):
                angle = random.uniform(0, math.tau)
                inner_r = 5
                outer_r = random.uniform(80, 200)
                x1 = int(SCREEN_W // 2 + inner_r * math.cos(angle))
                y1 = int(SCREEN_H // 2 + inner_r * math.sin(angle))
                x2 = int(SCREEN_W // 2 + outer_r * math.cos(angle))
                y2 = int(SCREEN_H // 2 + outer_r * math.sin(angle))
                pygame.draw.line(screen, (180, 180, 255), (x1, y1), (x2, y2), 1)

        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()

except (ImportError, RuntimeError) as e:
    # No display — render to GIF
    print(f"Display not available ({e}), rendering GIF...")

    from PIL import Image, ImageDraw

    total_frames = DURATION_SECONDS * FPS
    images = []

    print(f"Rendering {total_frames} frames ({DURATION_SECONDS}s @ {FPS}fps)...")
    start = time.time()

    for f in range(total_frames):
        screen_data = bytes([5, 5, 25]) * (SCREEN_W * SCREEN_H)
        buf = bytearray(screen_data)
        elapsed = f / FPS

        # We need to do pixel-level drawing — use PIL ImageDraw for simplicity
        img = Image.new('RGB', (SCREEN_W, SCREEN_H), (5, 5, 25))
        draw = ImageDraw.Draw(img)

        # Galaxy core glow
        core_x, core_y = SCREEN_W // 2, SCREEN_H // 2
        for gr in range(25, 0, -2):
            a = int((1.0 - gr / 25) * 60)
            if a < 2:
                continue
            r2 = max(1, int(gr * 0.8))
            draw.ellipse([core_x - gr, core_y - gr, core_x + gr, core_y + gr],
                         fill=(int(lerp(180, 255, 1 - gr / 25)),
                               int(lerp(160, 255, 1 - gr / 25)),
                               int(lerp(220, 255, 1 - gr / 25))))
        draw.ellipse([core_x - 5, core_y - 5, core_x + 5, core_y + 5],
                     fill=(255, 255, 255))

        # Draw nebula clouds
        for nc in nebula_clouds:
            nc.update(elapsed)
            cx = SCREEN_W // 2 + int(nc.cx)
            cy = SCREEN_H // 2 + int(nc.cy)
            r = int(nc.radius)
            for gr in range(r, 0, -5):
                a = int(nc.opacity * (1.0 - gr / r) * 255)
                if a < 3:
                    continue
                nr, ng, nb = nc.color
                draw.ellipse([cx - gr, cy - gr, cx + gr, cy + gr],
                             fill=(clamp(nr), clamp(ng), clamp(nb)))

        # Draw dust
        for dust in _dust_particles:
            dust.move()
            proj = project_3d(dust.x, dust.y, dust.z)
            if proj is None:
                continue
            sx, sy, radius, brightness = proj
            if 0 <= sx < SCREEN_W and 0 <= sy < SCREEN_H:
                v = int(60 * brightness)
                draw.ellipse([sx - 1, sy - 1, sx + 1, sy + 1],
                             fill=(v, v, v + 20))

        # Draw galaxy stars (with trails)
        galaxy_entries = []
        for gs in galaxy_stars:
            gs.move()
            proj = project_3d(gs.x, gs.y, gs.z)
            if proj is None:
                continue
            sx, sy, radius, brightness = proj
            if not (0 <= sx < SCREEN_W and 0 <= sy < SCREEN_H):
                continue
            galaxy_entries.append((gs.z, sx, sy, radius, gs))

        galaxy_entries.sort(key=lambda e: e[0])
        for gz, sx, sy, radius, gs in galaxy_entries:
            r, g, b = gs.color
            twinkle = 0.7 + 0.3 * math.sin(gs.twinkle_phase + elapsed * 0.5)
            r2 = clamp(int(r * brightness * twinkle))
            g2 = clamp(int(g * brightness * twinkle))
            b2 = clamp(int(b * brightness * twinkle))
            sz = max(1, radius)
            draw.ellipse([sx - sz, sy - sz, sx + sz, sy + sz],
                         fill=(r2, g2, b2))

        # Draw regular stars
        for star in stars:
            star.move()
            proj = project_3d(star.x, star.y, star.z)
            if proj is None:
                continue
            sx, sy, radius, brightness = proj
            if not (0 <= sx < SCREEN_W and 0 <= sy < SCREEN_H):
                continue
            r, g, b = star.color_at(elapsed)
            twinkle = 0.6 + 0.4 * math.sin(star.twinkle_phase)
            r2 = clamp(int(r * brightness * twinkle))
            g2 = clamp(int(g * brightness * twinkle))
            b2 = clamp(int(b * brightness * twinkle))
            sz = max(1, radius)
            draw.ellipse([sx - sz, sy - sz, sx + sz, sy + sz],
                         fill=(r2, g2, b2))

        # Draw shooting stars (with trails)
        for ss in shooting_stars:
            entry = ss.get()
            if entry is None:
                continue
            sx, sy, radius, brightness = entry
            if not (0 <= sx < SCREEN_W and 0 <= sy < SCREEN_H):
                continue
            r, g, b = ss.color
            alpha = min(1.0, ss.life / 20.0)
            r2 = clamp(int(r * brightness * alpha))
            g2 = clamp(int(g * brightness * alpha))
            b2 = clamp(int(b * brightness * alpha))
            sz = max(2, radius)
            draw.ellipse([sx - sz, sy - sz, sx + sz, sy + sz],
                         fill=(r2, g2, b2))
            # Draw trail (fading ghosting behind shooting star)
            for i, (tsx, tsy, tr, tb, tr2, tg, tb2) in enumerate(ss.trail):
                trail_alpha = (i / max(1, len(ss.trail))) ** 1.5
                tr2v = clamp(int(tr2 * trail_alpha))
                tg2v = clamp(int(tg * trail_alpha))
                tb2v = clamp(int(tb2 * trail_alpha))
                tr_sz = max(1, int(tr * 0.4))
                draw.ellipse([tsx - tr_sz, tsy - tr_sz, tsx + tr_sz, tsy + tr_sz],
                             fill=(tr2v, tg2v, tb2v))

        images.append(img)

        if (f + 1) % 50 == 0:
            elapsed_sec = time.time() - start
            print(f"  Frame {f+1}/{total_frames} ({elapsed_sec:.1f}s)...")

    images[0].save(
        OUTPUT_GIF,
        save_all=True,
        append_images=images[1:],
        duration=1000.0 / FPS,
        loop=0,
        optimize=True,
    )

    file_size = os.path.getsize(OUTPUT_GIF)
    print(f"Saved starfield_v2.gif  ->  {OUTPUT_GIF} ({file_size / 1024:.1f} KB)")
    print("Open it in your browser or image viewer.")
