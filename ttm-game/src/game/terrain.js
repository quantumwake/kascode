// ===== TERRAIN / MAP GENERATION =====
// Uses value noise for procedural generation

import { MAP_SIZE, TERRAIN } from './constants.js';

// ---- Value Noise (robust, no out-of-bounds issues) ----
class ValueNoise {
  constructor(seed = Math.random()) {
    // Build permutation table
    this.p = [];
    for (let i = 0; i < 256; i++) this.p[i] = i;

    // Fisher-Yates shuffle with LCG PRNG
    let s = Math.max(1, (seed * 65536) | 0); // ensure non-zero
    for (let i = 255; i > 0; i--) {
      s = (s * 1103515245 + 12345) & 0x7fffffff;
      const j = (s % (i + 1));
      [this.p[i], this.p[j]] = [this.p[j], this.p[i]];
    }
    // Extend to 512 for wraparound
    this.perm = new Array(512);
    for (let i = 0; i < 512; i++) this.perm[i] = this.p[i & 255];

    // Generate random gradient values for each cell corner
    this.values = new Float32Array(256);
    s = (s * 1103515245 + 12345) & 0x7fffffff;
    for (let i = 0; i < 256; i++) {
      s = (s * 1103515245 + 12345) & 0x7fffffff;
      this.values[i] = ((s & 0x7fffffff) / 0x7fffffff) * 2 - 1; // -1 to 1
    }
  }

  // Smoothstep interpolation
  fade(t) {
    return t * t * t * (t * (t * 6 - 15) + 10);
  }

  // Linear interpolation
  lerp(a, b, t) {
    return a + t * (b - a);
  }

  noise2D(x, y) {
    // Grid cell coordinates
    const xi = Math.floor(x) & 255;
    const yi = Math.floor(y) & 255;
    const x2 = (xi + 1) & 255;
    const y2 = (yi + 1) & 255;

    // Relative position within cell
    const xf = x - Math.floor(x);
    const yf = y - Math.floor(y);

    // Smoothstep
    const u = this.fade(xf);
    const v = this.fade(yf);

    // Corner values from permutation table
    const v00 = this.values[this.perm[xi + this.perm[yi]]];
    const v10 = this.values[this.perm[x2 + this.perm[yi]]];
    const v01 = this.values[this.perm[xi + this.perm[y2]]];
    const v11 = this.values[this.perm[x2 + this.perm[y2]]];

    // Bilinear interpolation
    const x1 = this.lerp(v00, v10, u);
    const x2 = this.lerp(v01, v11, u);
    return this.lerp(x1, x2, v);
  }

  octave2D(x, y, octaves, persistence) {
    let total = 0, frequency = 1, amplitude = 1, maxValue = 0;
    for (let i = 0; i < octaves; i++) {
      total += this.noise2D(x * frequency, y * frequency) * amplitude;
      maxValue += amplitude;
      amplitude *= persistence;
      frequency *= 2;
    }
    return total / maxValue;
  }
}

// ---- Map Generation ----

export function generateMap(seed) {
  const noise = new ValueNoise(seed);
  const moistureNoise = new ValueNoise(seed + 1000);
  const detailNoise = new ValueNoise(seed + 2000);

  const terrain = new Uint8Array(MAP_SIZE * MAP_SIZE);
  const features = new Uint8Array(MAP_SIZE * MAP_SIZE);
  const elevation = new Float32Array(MAP_SIZE * MAP_SIZE);

  const waterLevel = -0.05;

  for (let y = 0; y < MAP_SIZE; y++) {
    for (let x = 0; x < MAP_SIZE; x++) {
      const i = y * MAP_SIZE + x;
      const nx = x / MAP_SIZE;
      const ny = y / MAP_SIZE;

      // Elevation with edge mountains
      const elev = noise.octave2D(nx * 6, ny * 6, 5, 0.5);
      const distFromCenter = Math.sqrt(
        Math.pow((nx - 0.5) * 2, 2) + Math.pow((ny - 0.5) * 2, 2)
      );
      const edgeFactor = Math.max(0, (distFromCenter - 0.3) * 2);
      const finalElev = elev * 0.6 + edgeFactor * 0.4;
      elevation[i] = finalElev;

      const moist = moistureNoise.octave2D(nx * 8, ny * 8, 3, 0.5);
      const detail = detailNoise.noise2D(x * 0.05, y * 0.05) * 0.1;

      // Determine terrain type
      if (finalElev < waterLevel) {
        terrain[i] = TERRAIN.WATER;
      } else if (finalElev < waterLevel + 0.05) {
        terrain[i] = TERRAIN.GRASS;
      } else if (finalElev < 0.2) {
        terrain[i] = moist > 0.1 ? TERRAIN.GRASS : TERRAIN.DESERT;
      } else if (finalElev < 0.35) {
        terrain[i] = TERRAIN.HILLS;
      } else if (finalElev < 0.5) {
        terrain[i] = TERRAIN.MOUNTAIN;
      } else {
        terrain[i] = moist > 0 ? TERRAIN.SNOW : TERRAIN.MOUNTAIN;
      }

      // Features: trees on grassland
      if (terrain[i] === TERRAIN.GRASS && detail > 0.05 && Math.random() < 0.12) {
        features[i] = 1; // tree
      }
    }
  }

  return { terrain, features, elevation };
}

// ---- Find flat area for town/industry placement ----

export function findFlatArea(terrain, size, minElev, maxElev, rngSeed) {
  const candidates = [];
  const step = 16;
  let s = Math.max(1, (rngSeed * 65536) | 0);

  for (let y = 32; y < size - 32; y += step) {
    for (let x = 32; x < size - 32; x += step) {
      const i = y * size + x;
      if (terrain[i] !== TERRAIN.GRASS && terrain[i] !== TERRAIN.DESERT) continue;

      // Count flat neighbors
      let flatCount = 0;
      const radius = 10;
      for (let dy = -radius; dy <= radius; dy++) {
        for (let dx = -radius; dx <= radius; dx++) {
          const nx = x + dx, ny = y + dy;
          if (nx < 0 || nx >= size || ny < 0 || ny >= size) continue;
          const ni = ny * size + nx;
          if (terrain[ni] === TERRAIN.GRASS || terrain[ni] === TERRAIN.DESERT) {
            flatCount++;
          }
        }
      }
      if (flatCount > 60) {
        s = (s * 1103515245 + 12345) & 0x7fffffff;
        candidates.push({ x, y, score: flatCount + ((s & 0x7fffffff) / 0x7fffffff) * 20 });
      }
    }
  }

  candidates.sort((a, b) => b.score - a.score);
  return candidates.length > 0 ? candidates[0] : null;
}

// ---- Find water edge for docks ----

export function findWaterEdge(terrain, size, rngSeed) {
  const candidates = [];
  const step = 16;
  let s = Math.max(1, (rngSeed * 65536) | 0);

  for (let y = 32; y < size - 32; y += step) {
    for (let x = 32; x < size - 32; x += step) {
      const i = y * size + x;
      if (terrain[i] !== TERRAIN.WATER) continue;

      // Check if adjacent to land
      let hasLand = false;
      for (let dy = -1; dy <= 1 && !hasLand; dy++) {
        for (let dx = -1; dx <= 1 && !hasLand; dx++) {
          const nx = x + dx, ny = y + dy;
          if (nx >= 0 && nx < size && ny >= 0 && ny < size) {
            const ni = ny * size + nx;
            if (terrain[ni] !== TERRAIN.WATER) hasLand = true;
          }
        }
      }
      if (hasLand) {
        s = (s * 1103515245 + 12345) & 0x7fffffff;
        candidates.push({ x, y, score: (s & 0x7fffffff) / 0x7fffffff });
      }
    }
  }

  candidates.sort((a, b) => b.score - a.score);
  return candidates.length > 0 ? candidates[0] : null;
}

// ---- Town name generation ----
const townNames = ['Springfield','Riverside','Lakewood','Fairview','Oakdale','Maplewood',
  'Cedarburg','Brookfield','Pineville','Ashford','Bridgeton','Edgewater',
  'Greenfield','Hawthorne','Kingsley','Madison','Parkside','Claremont',
  'Doverton','Summertown','Thornbury','Valleyford','Woodstock','Elmsworth'];

export function generateTownName(index, rngSeed) {
  let s = Math.max(1, ((rngSeed + index * 1000) * 65536) | 0);
  s = (s * 1103515245 + 12345) & 0x7fffffff;
  return townNames[s % townNames.length];
}
