"""
3D Starfield - Interactive live 3D starfield rendered with Pygame.
"""

import pygame
import random
import sys
import math

# ─── Configuration ───────────────────────────────────────────────
SCREEN_W, SCREEN_H = 1200, 1000
NUM_STARS = 600
STAR_DEPTH = 2000
FOCAL_LENGTH = 500
BG_COLOR = (10, 10, 46)

# Star color palettes: (r, g, b)
STAR_COLORS = [
    (255, 255, 255),    # white
    (173, 216, 230),    # lightblue
    (255, 255, 224),    # lightyellow
    (255, 182, 193),    # lightpink
    (170, 204, 255),    # soft blue
    (255, 221, 170),    # soft yellow
    (221, 170, 255),    # soft purple
]

FPS = 60


class Star:
    """Single star with 3D position and visual properties."""

    __slots__ = ('x', 'y', 'z', 'base_r', 'base_g', 'base_b', 'speed')

    def __init__(self):
        self.reset()

    def reset(self):
        self.x = random.uniform(-600, 600)
        self.y = random.uniform(-500, 500)
        self.z = random.uniform(10, STAR_DEPTH)
        self.base_r, self.base_g, self.base_b = random.choice(STAR_COLORS)
        self.speed = random.uniform(2.0, 5.0)

    def move(self):
        self.z -= self.speed
        if self.z <= 1:
            self.reset()

    def project(self):
        """Perspective-project onto screen coordinates."""
        if self.z < 1:
            return None
        scale = FOCAL_LENGTH / self.z
        sx = SCREEN_W // 2 + int(self.x * scale)
        sy = SCREEN_H // 2 + int(self.y * scale)
        # Size grows as star gets closer (clamped)
        radius = max(1, min(5, int(300.0 / self.z)))
        # Brightness increases as star gets closer
        brightness = min(1.0, 500.0 / self.z)
        return sx, sy, radius, brightness


# ─── Build star field ────────────────────────────────────────────
stars = [Star() for _ in range(NUM_STARS)]

# ─── Pygame setup ────────────────────────────────────────────────
pygame.init()
screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
pygame.display.set_caption("3D Starfield")
clock = pygame.time.Clock()
running = True

print("Starfield running — press ESC or close the window to stop.")

# ─── Main loop ───────────────────────────────────────────────────
frame = 0
while running:
    frame += 1
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                running = False

    # Update stars
    for star in stars:
        star.move()

    # Draw stars
    screen.fill(BG_COLOR)

    for star in stars:
        result = star.project()
        if result is None:
            continue
        sx, sy, radius, brightness = result

        # Skip stars outside screen
        if sx < -radius or sx > SCREEN_W + radius or sy < -radius or sy > SCREEN_H + radius:
            continue

        r = min(255, int(star.base_r * brightness))
        g = min(255, int(star.base_g * brightness))
        b = min(255, int(star.base_b * brightness))

        # Draw star as a small filled circle
        pygame.draw.circle(screen, (r, g, b), (sx, sy), radius)

    pygame.display.flip()
    clock.tick(FPS)

pygame.quit()
