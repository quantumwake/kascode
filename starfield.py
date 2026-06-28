"""
3D Starfield - Interactive 3D starfield rendered with Pygame.
Falls back to GIF generation if no display is available.
"""

import random
import os
import sys

# ─── Configuration ───────────────────────────────────────────────
SCREEN_W, SCREEN_H = 1200, 1000
NUM_STARS = 600
STAR_DEPTH = 2000
FOCAL_LENGTH = 500
BG_COLOR = (10, 10, 46)
OUTPUT_GIF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "starfield.gif")
DURATION_SECONDS = 15
FPS = 30

STAR_COLORS = [
    (255, 255, 255),
    (173, 216, 230),
    (255, 255, 224),
    (255, 182, 193),
    (170, 204, 255),
    (255, 221, 170),
    (221, 170, 255),
]


class Star:
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
        if self.z < 1:
            return None
        scale = FOCAL_LENGTH / self.z
        sx = SCREEN_W // 2 + int(self.x * scale)
        sy = SCREEN_H // 2 + int(self.y * scale)
        radius = max(1, min(5, int(300.0 / self.z)))
        brightness = min(1.0, 500.0 / self.z)
        return sx, sy, radius, brightness


# ─── Try live mode with Pygame ──────────────────────────────────
try:
    import pygame

    stars = [Star() for _ in range(NUM_STARS)]
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
    pygame.display.set_caption("3D Starfield")
    clock = pygame.time.Clock()
    running = True

    print("Starfield running — press ESC or close the window to stop.")

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False

        for star in stars:
            star.move()

        screen.fill(BG_COLOR)

        for star in stars:
            result = star.project()
            if result is None:
                continue
            sx, sy, radius, brightness = result

            if sx < -radius or sx > SCREEN_W + radius or sy < -radius or sy > SCREEN_H + radius:
                continue

            r = min(255, int(star.base_r * brightness))
            g = min(255, int(star.base_g * brightness))
            b = min(255, int(star.base_b * brightness))

            pygame.draw.circle(screen, (r, g, b), (sx, sy), radius)

        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()

except (ImportError, RuntimeError) as e:
    # No display available — render to GIF instead
    print(f"Display not available ({e}), rendering GIF...")

    from PIL import Image

    stars = [Star() for _ in range(NUM_STARS)]
    total_frames = DURATION_SECONDS * FPS
    images = []

    print(f"Rendering {total_frames} frames ({DURATION_SECONDS}s @ {FPS}fps)...")
    for f in range(total_frames):
        screen_data = list(BG_COLOR) * (SCREEN_W * SCREEN_H)

        for star in stars:
            star.move()
            result = star.project()
            if result is None:
                continue
            sx, sy, radius, brightness = result

            if sx < -radius or sx > SCREEN_W + radius or sy < -radius or sy > SCREEN_H + radius:
                continue

            r = min(255, int(star.base_r * brightness))
            g = min(255, int(star.base_g * brightness))
            b = min(255, int(star.base_b * brightness))

            # Draw filled circle on the raw pixel buffer
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    if dx * dx + dy * dy <= radius * radius:
                        px = sx + dx
                        py = sy + dy
                        if 0 <= px < SCREEN_W and 0 <= py < SCREEN_H:
                            idx = py * SCREEN_W + px
                            if screen_data[idx * 3] < r:  # lighten
                                screen_data[idx * 3] = r
                                screen_data[idx * 3 + 1] = g
                                screen_data[idx * 3 + 2] = b

        img = Image.frombytes('RGB', (SCREEN_W, SCREEN_H), bytes(screen_data))
        images.append(img)

        if (f + 1) % 50 == 0:
            print(f"  Frame {f+1}/{total_frames}...")

    images[0].save(
        OUTPUT_GIF,
        save_all=True,
        append_images=images[1:],
        duration=1000.0 / FPS,
        loop=0,
        optimize=True,
    )

    file_size = os.path.getsize(OUTPUT_GIF)
    print(f"Saved starfield.gif  ->  {OUTPUT_GIF} ({file_size / 1024:.1f} KB)")
    print("Open it in your browser or image viewer.")
