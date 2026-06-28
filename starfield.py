"""
3D Starfield - Renders an animated 3D starfield projection as a GIF file.
"""

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import PillowWriter
import random
import sys
import os

# ─── Configuration ───────────────────────────────────────────────
NUM_STARS = 800
STAR_FIELD_DEPTH = 2000
FOCAL_LENGTH = 500
BG_COLOR = "#0a0a2e"
OUTPUT_GIF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "starfield.gif")
DURATION_SECONDS = 15
FPS = 30

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

# ─── Generate frames ─────────────────────────────────────────────
total_frames = DURATION_SECONDS * FPS
fig, ax = plt.subplots(figsize=(12, 10))
fig.patch.set_facecolor(BG_COLOR)
ax.set_facecolor(BG_COLOR)
ax.set_xlim(-500, 500)
ax.set_ylim(-500, 500)
ax.set_aspect("equal")
ax.axis("off")
fig.suptitle("3D Starfield Projection", color="white", fontsize=14, y=0.98)

scatter = ax.scatter([], [], s=[], c=[], edgecolors="none", zorder=2)

frame_count = [0]  # mutable counter for closure

def _draw_frame(frame):
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
        scatter.set_offsets(arr)
        scatter.set_sizes(np.array(sizes) * 20)
        scatter.set_facecolors(colors)
        scatter.set_alpha(0.9)
    else:
        scatter.set_offsets(np.empty((0, 2)))

    frame_count[0] += 1
    return scatter,


anim = plt.FuncAnimation(
    fig,
    _draw_frame,
    frames=total_frames,
    interval=1000.0 / FPS,
    blit=False,
    cache_frame_data=False,
)

print(f"Rendering {total_frames} frames ({DURATION_SECONDS}s @ {FPS}fps)...")
anim.save(OUTPUT_GIF, writer=PillowWriter(fps=FPS), savefig_dict={"facecolor": BG_COLOR})
print(f"Saved starfield.gif  ->  {OUTPUT_GIF}")
print("Open it in your browser or image viewer!")
plt.close(fig)
