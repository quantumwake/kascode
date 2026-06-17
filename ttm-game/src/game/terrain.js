import { MAP_SIZE, TERRAIN } from './constants.js';

// Simplex-like noise for terrain generation
class Noise {
  constructor(seed = 42) {
    this.perm = new Uint8Array(512);
    this.seed(seed);
  }

  seed(s) {
    const p = new Uint8Array(256);
    for (let i = 0; i < 256; i++) p[i] = i;
    let rng = s;
    for (let i = 255; i > 0; i--) {
      rng = (rng * 16807 + 0) % 2147483647;
      const j = rng % (i + 1);
      [p[i], p[j]] = [p[j], p[i]];
    }
    for (let i = 0; i < 512; i++) this.perm[i] = p[i & 255];
  }

  fade(t) { return t * t * t * (t * (t * 6 - 15) + 10); }
  lerp(a, b, t) { return a + t * (b - a); }
  grad(hash, x, y) {
    const h = hash & 3;
    const u = h < 2 ? x : y;
    const v = h < 2 ? y : x;
    return ((h & 1) ? -u : u) + ((h & 2) ? -v : v);
  }

  noise2D(x, y) {
    const X = Math.floor(x) & 255;
    const Y = Math.floor(y) & 255;
    x -= Math.floor(x);
    y -= Math.floor(y);
    const u = this.fade(x);
    const v = this.fade(y);
    const A = this.perm[X] + Y;
    const B = this.perm[X + 1] + Y;
    return this.lerp(
      this.lerp(this.grad(this.perm[A], x, y), this.grad(this.perm[B], x - 1, y), u),
      this.lerp(this.grad(this.perm[A + 1], x, y - 1), this.grad(this.perm[B + 1], x - 1, y - 1), u),
      v
    ) / 2;
  }

  octave(x, y, octaves, persistence) {
    let total = 0;
    let frequency = 1;
    let amplitude = 1;
    let maxVal = 0;
    for (let i = 0; i < octaves; i++) {
      total += this.noise2D(x * frequency, y * frequency) * amplitude;
      maxVal += amplitude;
      amplitude *= persistence;
      frequency *= 2;
    }
    return total / maxVal;
  }
}

export function generateMap(seed = 42) {
  const noise = new Noise(seed);
  const waterNoise = new Noise(seed + 1000);
  const mapSize = MAP_SIZE;

  const terrain = new Uint8Array(mapSize * mapSize);
  const features = new Uint8Array(mapSize * mapSize);
  const elevation = new Float32Array(mapSize * mapSize);

  for (let y = 0; y < mapSize; y++) {
    for (let x = 0; x < mapSize; x++) {
      const idx = y * mapSize + x;
      const scale = 0.008;
      const elev = noise.octave(x * scale, y * scale, 5, 0.5);
      elevation[idx] = elev;
      const waterVal = waterNoise.octave(x * scale * 1.5, y * scale * 1.5, 3, 0.5);

      if (elev + waterVal * 0.3 < -0.05) {
        terrain[idx] = TERRAIN.WATER;
      } else if (elev > 0.45) {
        terrain[idx] = TERRAIN.MOUNTAIN;
      } else if (elev > 0.25) {
        terrain[idx] = TERRAIN.HILLS;
      } else if (elev > 0.15) {
        const desert = noise.noise2D(x * 0.02, y * 0.02);
        terrain[idx] = desert > 0.3 ? TERRAIN.DESERT : TERRAIN.GRASS;
      } else if (elev < -0.15) {
        terrain[idx] = TERRAIN.SNOW;
      } else {
        terrain[idx] = TERRAIN.GRASS;
      }

      if (terrain[idx] === TERRAIN.GRASS) {
        const treeVal = noise.noise2D(x * 0.05 + 100, y * 0.05 + 100);
        if (treeVal > 0.4) features[idx] = 1;
      }
    }
  }

  // Smooth water edges
  for (let y = 1; y < mapSize - 1; y++) {
    for (let x = 1; x < mapSize - 1; x++) {
      const idx = y * mapSize + x;
      if (terrain[idx] === TERRAIN.WATER) {
        let waterCount = 0;
        for (let dy = -1; dy <= 1; dy++) {
          for (let dx = -1; dx <= 1; dx++) {
            if (terrain[(y + dy) * mapSize + (x + dx)] === TERRAIN.WATER) waterCount++;
          }
        }
        if (waterCount < 7) terrain[idx] = TERRAIN.GRASS;
      }
    }
  }

  return { terrain, features, elevation };
}

export function findFlatArea(terrain, mapSize, minSize, seed) {
  let rng = seed;
  for (let a = 0; a < 500; a++) {
    rng = (rng * 16807) % 2147483647;
    const cx = rng % (mapSize - minSize * 4);
    rng = (rng * 16807) % 2147483647;
    const cy = rng % (mapSize - minSize * 4);
    let suitable = true;
    for (let dy = -minSize; dy <= minSize && suitable; dy++) {
      for (let dx = -minSize; dx <= minSize && suitable; dx++) {
        if (terrain[(cy + dy) * mapSize + (cx + dx)] !== TERRAIN.GRASS) suitable = false;
      }
    }
    if (suitable) return { x: cx, y: cy };
  }
  return null;
}

export function findWaterEdge(terrain, mapSize, seed) {
  let rng = seed;
  for (let a = 0; a < 500; a++) {
    rng = (rng * 16807) % 2147483647;
    const x = rng % mapSize;
    rng = (rng * 16807) % 2147483647;
    const y = rng % mapSize;
    if (terrain[y * mapSize + x] === TERRAIN.GRASS) {
      const dirs = [[-1,0],[1,0],[0,-1],[0,1]];
      for (const [dx, dy] of dirs) {
        const nx = x + dx, ny = y + dy;
        if (nx >= 0 && nx < mapSize && ny >= 0 && ny < mapSize) {
          if (terrain[ny * mapSize + nx] === TERRAIN.WATER) return { x, y };
        }
      }
    }
  }
  return null;
}
