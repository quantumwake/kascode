"""
3D Starfield - Interactive live 3D starfield projection.
"""

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
import random

# ─── Configuration ───────────────────────────────────────────────
NUM_STARS = 800
STAR_FIELD_DEPTH = 2000
FOCAL_LENGTH = 500
BG_COLOR = "#0a0a2e"

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

# ─── Matplotlib figure ───────────────────────────────────────────
fig, ax = plt.subplots(figsize=(12, 10))
fig.patch.set_facecolor(BG_COLOR)
ax.set_facecolor(BG_COLOR)
ax.set_xlim(-500, 500)
ax.set_ylim(-500, 500)
ax.set_aspect("equal")
ax.axis("off")
fig.suptitle("3D Starfield Projection", color="white", fontsize=14, y=0.98)

# Pre-allocate arrays for in-place updates (avoid re-allocating every frame)
max_visible = NUM_STARS
_x = np.full(max_visible, np.nan)
_y = np.full(max_visible, np.nan)
_sizes = np.full(max_visible, 0.0)
_colors = np.empty(max_visible, dtype=object)
_visible_count = 0

# Single scatter artist
scatter = ax.scatter([], [], s=[], c=[], edgecolors="none", zorder=2)


def _init():
    """Draw initial frame so the window isn't empty."""
    return _update(0)


def _update(frame):
    global _visible_count

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
        scatter.set_sizes(np.array(sizes) * 25)
        scatter.set_facecolors(colors)
        scatter.set_edgecolors("none")
        scatter.set_alpha(0.9)
    else:
        scatter.set_offsets(np.empty((0, 2)))

    return scatter,


anim = FuncAnimation(
    fig,
    _update,
    init_func=_init,
    frames=None,
    interval=16,          # ~60 fps
    blit=False,
    cache_frame_data=False,
)

print("Starfield running — press Ctrl+C to stop.")
plt.show()
