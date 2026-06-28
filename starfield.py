"""
3D Starfield - Renders an animated 3D starfield projection as a GIF file.
"""

import numpy as np
import matplotlib.pyplot as plt
import random
import os
from PIL import Image

# ─── Configuration ───────────────────────────────────────────────
NUM_STARS = 800
STAR_FIELD_DEPTH = 2000
FOCAL_LENGTH = 500
OUTPUT_GIF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "starfield.gif")
DURATION_SECONDS = 15
FPS = 30
TOTAL_FRAMES = DURATION_SECONDS * FPS

STAR_COLORS = [
    "white",
    "lightblue",
    "lightyellow",
    "lightpink",
    "#aaccff",
    "#ffddaa",
    "#ddaaff",
]


# ─── Star class ──────────────────────────────────────────────────
class Star:
    def __init__(self):
        self.reset()

    def reset(self):
        self.x = random.uniform(-500, 500)
        self.y = random.uniform(-500, 500)
        self.z = random.uniform(10, STAR_FIELD_DEPTH)
        self.base_size = random.uniform(1.0, 3.0)
        self.color = random.choice(STAR_COLORS)
        self.speed = random.uniform(1.5, 4.0)

    def move(self, dt):
        self.z -= self.speed * dt
        if self.z <= 1:
            self.reset()

    def project(self):
        if self.z < 1:
            return None, None
        scale = FOCAL_LENGTH / self.z
        return self.x * scale, self.y * scale


stars = [Star() for _ in range(NUM_STARS)]

# ─── Render frames manually ──────────────────────────────────────
print(f"Rendering {TOTAL_FRAMES} frames ({DURATION_SECONDS}s @ {FPS}fps)...")

fig, ax = plt.subplots(figsize=(12, 10), facecolor="#0a0a2e")
ax.set_facecolor("#0a0a2e")
ax.set_xlim(-500, 500)
ax.set_ylim(-500, 500)
ax.set_aspect("equal")
ax.axis("off")

images = []
for f in range(TOTAL_FRAMES):
    ax.clear()
    ax.set_facecolor("#0a0a2e")
    ax.set_xlim(-500, 500)
    ax.set_ylim(-500, 500)
    ax.set_aspect("equal")
    ax.axis("off")

    positions = []
    sizes = []
    colors = []

    for star in stars:
        star.move(1)
        sx, sy = star.project()
        if sx is None:
            continue
        brightness = min(1.0, 500.0 / star.z)
        positions.append([sx, sy])
        sizes.append(star.base_size * (500.0 / star.z))
        colors.append(star.color)

    if positions:
        arr = np.array(positions)
        ax.scatter(arr[:, 0], arr[:, 1], s=np.array(sizes) * 20,
                   c=colors, edgecolors="none", alpha=0.9)

    fig.canvas.draw()
    # Convert figure to PIL Image
    buf = np.frombuffer(fig.canvas.tostring_rgb(), dtype=np.uint8)
    buf.shape = (fig.canvas.get_width_height()[::-1] + (3,))
    img = Image.fromarray(buf)
    images.append(img)

    if (f + 1) % 50 == 0:
        print(f"  Frame {f+1}/{TOTAL_FRAMES}...")

plt.close(fig)

# Save as GIF
print(f"Saving starfield.gif ({os.path.getsize(OUTPUT_GIF) if os.path.exists(OUTPUT_GIF) else 0} bytes)...")
if os.path.exists(OUTPUT_GIF):
    os.remove(OUTPUT_GIF)
images[0].save(
    OUTPUT_GIF,
    save_all=True,
    append_images=images[1:],
    duration=1000.0 / FPS,
    loop=0,
    optimize=True,
)

file_size = os.path.getsize(OUTPUT_GIF)
print(f"Done! Saved {OUTPUT_GIF} ({file_size / 1024:.1f} KB)")
