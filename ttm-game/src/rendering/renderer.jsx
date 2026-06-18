// ===== CANVAS RENDERER — Isometric 3D Style =====

import { useRef, useEffect, useCallback, useMemo } from 'react';
import {
  MAP_SIZE, TILE_SIZE, TERRAIN, TERRAIN_COLORS, TILE, SURFACE_COLORS,
  VEHICLE_DEFS, VEHICLE_CLASSES
} from '../game/constants.js';

// ---- Isometric projection helpers ----

const ISO_W = 64;  // tile width in pixels
const ISO_H = 32;  // tile height in pixels
const ISO_DEPTH = 8; // 3D depth for terrain blocks

function isoToScreen(x, y, elevation = 0) {
  const sx = (x - y) * ISO_W / 2;
  const sy = (x + y) * ISO_H / 2 - (elevation || 0) * ISO_DEPTH;
  return [sx, sy];
}

function drawIsoTile(ctx, x, y, color, depth = 0) {
  const [sx, sy] = isoToScreen(x, y, depth);
  // Top face (diamond)
  ctx.beginPath();
  ctx.moveTo(sx, sy - ISO_H / 2);
  ctx.lineTo(sx + ISO_W / 2, sy);
  ctx.lineTo(sx, sy + ISO_H / 2);
  ctx.lineTo(sx - ISO_W / 2, sy);
  ctx.closePath();
  ctx.fillStyle = color;
  ctx.fill();
  // Left face (3D side)
  if (depth > 0) {
    ctx.beginPath();
    ctx.moveTo(sx - ISO_W / 2, sy);
    ctx.lineTo(sx, sy + ISO_H / 2);
    ctx.lineTo(sx, sy + ISO_H / 2 + ISO_DEPTH * depth);
    ctx.lineTo(sx - ISO_W / 2, sy + ISO_DEPTH * depth);
    ctx.closePath();
    ctx.fillStyle = shadeColor(color, -30);
    ctx.fill();
    // Right face (3D side)
    ctx.beginPath();
    ctx.moveTo(sx + ISO_W / 2, sy);
    ctx.lineTo(sx, sy + ISO_H / 2);
    ctx.lineTo(sx, sy + ISO_H / 2 + ISO_DEPTH * depth);
    ctx.lineTo(sx + ISO_W / 2, sy + ISO_DEPTH * depth);
    ctx.closePath();
    ctx.fillStyle = shadeColor(color, -50);
    ctx.fill();
  }
}

function shadeColor(color, percent) {
  let r, g, b;
  if (color.startsWith('#')) {
    const hex = color.slice(1);
    r = parseInt(hex.substring(0, 2), 16);
    g = parseInt(hex.substring(2, 4), 16);
    b = parseInt(hex.substring(4, 6), 16);
  } else if (color.startsWith('rgb')) {
    const match = color.match(/(\d+)/g);
    if (match) { r = +match[0]; g = +match[1]; b = +match[2]; }
    else return color;
  } else return color;
  r = Math.max(0, Math.min(255, r + percent));
  g = Math.max(0, Math.min(255, g + percent));
  b = Math.max(0, Math.min(255, b + percent));
  return `rgb(${r},${g},${b})`;
}

// ---- Pre-rendered isometric tile sprites ----

const tileCache = new Map();

function getIsoTile(terrainType, surfaceType, featureType, elevation) {
  const key = `${terrainType}_${surfaceType}_${featureType}_${elevation || 0}`;
  if (tileCache.has(key)) return tileCache.get(key);

  const canvas = document.createElement('canvas');
  canvas.width = ISO_W * 2;
  canvas.height = (ISO_H + ISO_DEPTH * (elevation || 0) + ISO_H) * 2;
  const ctx = canvas.getContext('2d');

  // Center the tile
  const cx = canvas.width / 2;
  const cy = canvas.height / 2;
  const [sx, sy] = isoToScreen(0, 0, elevation || 0);

  // Terrain base color with variation
  const baseColor = TERRAIN_COLORS[terrainType] || '#4a8c3f';
  const depth = Math.max(1, Math.floor((elevation || 0) * 3));

  // Draw 3D tile
  // Top face
  ctx.beginPath();
  ctx.moveTo(cx + sx, cy + sy - ISO_H / 2);
  ctx.lineTo(cx + sx + ISO_W / 2, cy + sy);
  ctx.lineTo(cx + sx, cy + sy + ISO_H / 2);
  ctx.lineTo(cx + sx - ISO_W / 2, cy + sy);
  ctx.closePath();
  ctx.fillStyle = baseColor;
  ctx.fill();

  // Add terrain texture on top face
  if (terrainType === TERRAIN.WATER) {
    ctx.fillStyle = 'rgba(100,180,255,0.3)';
    ctx.beginPath();
    ctx.moveTo(cx + sx - ISO_W * 0.3, cy + sy);
    ctx.lineTo(cx + sx + ISO_W * 0.1, cy + sy - ISO_H * 0.15);
    ctx.lineTo(cx + sx + ISO_W * 0.3, cy + sy);
    ctx.lineTo(cx + sx - ISO_W * 0.1, cy + sy + ISO_H * 0.15);
    ctx.closePath();
    ctx.fill();
  } else if (terrainType === TERRAIN.GRASS) {
    // Grass tufts
    ctx.fillStyle = 'rgba(30,100,20,0.4)';
    for (let i = 0; i < 5; i++) {
      const gx = cx + sx + (Math.sin(i * 2.3) * ISO_W * 0.3);
      const gy = cy + sy + (Math.cos(i * 1.7) * ISO_H * 0.2);
      ctx.fillRect(gx, gy, 3, 2);
    }
  } else if (terrainType === TERRAIN.DESERT) {
    ctx.fillStyle = 'rgba(200,170,100,0.3)';
    for (let i = 0; i < 4; i++) {
      ctx.beginPath();
      ctx.arc(cx + sx + Math.sin(i * 2) * ISO_W * 0.25, cy + sy + Math.cos(i * 3) * ISO_H * 0.15, 2, 0, Math.PI * 2);
      ctx.fill();
    }
  } else if (terrainType === TERRAIN.SNOW) {
    ctx.fillStyle = 'rgba(255,255,255,0.5)';
    for (let i = 0; i < 6; i++) {
      ctx.beginPath();
      ctx.arc(cx + sx + Math.sin(i * 1.5) * ISO_W * 0.3, cy + sy + Math.cos(i * 2.1) * ISO_H * 0.2, 1.5, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  // Left face (3D side)
  if (depth > 0) {
    ctx.beginPath();
    ctx.moveTo(cx + sx - ISO_W / 2, cy + sy);
    ctx.lineTo(cx + sx, cy + sy + ISO_H / 2);
    ctx.lineTo(cx + sx, cy + sy + ISO_H / 2 + ISO_DEPTH * depth);
    ctx.lineTo(cx + sx - ISO_W / 2, cy + sy + ISO_DEPTH * depth);
    ctx.closePath();
    ctx.fillStyle = shadeColor(baseColor, -30);
    ctx.fill();

    // Right face (3D side)
    ctx.beginPath();
    ctx.moveTo(cx + sx + ISO_W / 2, cy + sy);
    ctx.lineTo(cx + sx, cy + sy + ISO_H / 2);
    ctx.lineTo(cx + sx, cy + sy + ISO_H / 2 + ISO_DEPTH * depth);
    ctx.lineTo(cx + sx + ISO_W / 2, cy + sy + ISO_DEPTH * depth);
    ctx.closePath();
    ctx.fillStyle = shadeColor(baseColor, -50);
    ctx.fill();
  }

  // ---- Surface layer ----
  if (surfaceType === TILE.ROAD) {
    const roadColor = '#555';
    ctx.beginPath();
    ctx.moveTo(cx + sx, cy + sy - ISO_H * 0.35);
    ctx.lineTo(cx + sx + ISO_W * 0.3, cy + sy);
    ctx.lineTo(cx + sx, cy + sy + ISO_H * 0.35);
    ctx.lineTo(cx + sx - ISO_W * 0.3, cy + sy);
    ctx.closePath();
    ctx.fillStyle = roadColor;
    ctx.fill();
    // Road markings (center dashes)
    ctx.fillStyle = '#dd8';
    ctx.fillRect(cx + sx - 1, cy + sy - ISO_H * 0.2, 2, ISO_H * 0.15);
    ctx.fillRect(cx + sx - 1, cy + sy + ISO_H * 0.05, 2, ISO_H * 0.15);
  } else if (surfaceType === TILE.RAIL) {
    // Railroad ties
    ctx.fillStyle = '#5a3a1a';
    for (let i = -3; i <= 3; i++) {
      const ry = cy + sy + i * 4;
      ctx.fillRect(cx + sx - ISO_W * 0.2, ry, ISO_W * 0.4, 2);
    }
    // Rails
    ctx.fillStyle = '#aaa';
    ctx.fillRect(cx + sx - ISO_W * 0.12, cy + sy - ISO_H * 0.35, 2, ISO_H * 0.7);
    ctx.fillRect(cx + sx + ISO_W * 0.1 - 2, cy + sy - ISO_H * 0.35, 2, ISO_H * 0.7);
  } else if (surfaceType === TILE.STATION) {
    // Train station platform
    ctx.fillStyle = '#2196F3';
    ctx.beginPath();
    ctx.moveTo(cx + sx, cy + sy - ISO_H * 0.4);
    ctx.lineTo(cx + sx + ISO_W * 0.45, cy + sy);
    ctx.lineTo(cx + sx, cy + sy + ISO_H * 0.4);
    ctx.lineTo(cx + sx - ISO_W * 0.45, cy + sy);
    ctx.closePath();
    ctx.fill();
    // Platform edge
    ctx.fillStyle = '#fff';
    ctx.fillRect(cx + sx - ISO_W * 0.45, cy + sy - 1, ISO_W * 0.9, 3);
  } else if (surfaceType === TILE.BUS_STOP) {
    ctx.fillStyle = '#E65100';
    ctx.beginPath();
    ctx.moveTo(cx + sx, cy + sy - ISO_H * 0.3);
    ctx.lineTo(cx + sx + ISO_W * 0.2, cy + sy);
    ctx.lineTo(cx + sx, cy + sy + ISO_H * 0.3);
    ctx.lineTo(cx + sx - ISO_W * 0.2, cy + sy);
    ctx.closePath();
    ctx.fill();
    // Sign
    ctx.fillStyle = '#fff';
    ctx.fillRect(cx + sx - 2, cy + sy - ISO_H * 0.25, 4, ISO_H * 0.35);
  } else if (surfaceType === TILE.TRUCK_STOP) {
    ctx.fillStyle = '#8B6914';
    ctx.beginPath();
    ctx.moveTo(cx + sx, cy + sy - ISO_H * 0.3);
    ctx.lineTo(cx + sx + ISO_W * 0.25, cy + sy);
    ctx.lineTo(cx + sx, cy + sy + ISO_H * 0.3);
    ctx.lineTo(cx + sx - ISO_W * 0.25, cy + sy);
    ctx.closePath();
    ctx.fill();
  } else if (surfaceType === TILE.AIRPORT) {
    // Runway
    ctx.fillStyle = '#666';
    ctx.beginPath();
    ctx.moveTo(cx + sx, cy + sy - ISO_H * 0.45);
    ctx.lineTo(cx + sx + ISO_W * 0.4, cy + sy);
    ctx.lineTo(cx + sx, cy + sy + ISO_H * 0.45);
    ctx.lineTo(cx + sx - ISO_W * 0.4, cy + sy);
    ctx.closePath();
    ctx.fill();
    // Center line
    ctx.fillStyle = '#fff';
    ctx.fillRect(cx + sx - 1, cy + sy - ISO_H * 0.4, 2, ISO_H * 0.8);
  } else if (surfaceType === TILE.DOCK) {
    // Wooden pier
    ctx.fillStyle = '#6B4226';
    ctx.beginPath();
    ctx.moveTo(cx + sx, cy + sy - ISO_H * 0.4);
    ctx.lineTo(cx + sx + ISO_W * 0.45, cy + sy);
    ctx.lineTo(cx + sx, cy + sy + ISO_H * 0.4);
    ctx.lineTo(cx + sx - ISO_W * 0.45, cy + sy);
    ctx.closePath();
    ctx.fill();
    // Bollards
    ctx.fillStyle = '#333';
    ctx.beginPath(); ctx.arc(cx + sx - ISO_W * 0.2, cy + sy - ISO_H * 0.1, 3, 0, Math.PI * 2); ctx.fill();
    ctx.beginPath(); ctx.arc(cx + sx + ISO_W * 0.2, cy + sy + ISO_H * 0.1, 3, 0, Math.PI * 2); ctx.fill();
  } else if (surfaceType === TILE.BRIDGE) {
    ctx.fillStyle = '#777';
    ctx.beginPath();
    ctx.moveTo(cx + sx, cy + sy - ISO_H * 0.35);
    ctx.lineTo(cx + sx + ISO_W * 0.35, cy + sy);
    ctx.lineTo(cx + sx, cy + sy + ISO_H * 0.35);
    ctx.lineTo(cx + sx - ISO_W * 0.35, cy + sy);
    ctx.closePath();
    ctx.fill();
    // Bridge rails
    ctx.fillStyle = '#999';
    ctx.fillRect(cx + sx - ISO_W * 0.35, cy + sy - 1, ISO_W * 0.7, 2);
  } else if (surfaceType === TILE.SIGNAL) {
    ctx.fillStyle = '#c00';
    ctx.fillRect(cx + sx - 3, cy + sy - ISO_H * 0.25, 6, ISO_H * 0.5);
    ctx.fillStyle = '#ff0';
    ctx.beginPath(); ctx.arc(cx + sx, cy + sy - ISO_H * 0.15, 4, 0, Math.PI * 2); ctx.fill();
  }

  // ---- Features (buildings, trees) ----
  if (featureType === 1) {
    // Tree — 3D trunk + canopy
    ctx.fillStyle = '#5a3a1a';
    ctx.fillRect(cx + sx - 3, cy + sy - 5, 6, 12);
    ctx.fillStyle = '#2d7a1e';
    ctx.beginPath(); ctx.arc(cx + sx, cy + sy - 12, 12, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = '#1a5a10';
    ctx.beginPath(); ctx.arc(cx + sx - 3, cy + sy - 15, 8, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = 'rgba(100,200,50,0.3)';
    ctx.beginPath(); ctx.arc(cx + sx + 4, cy + sy - 10, 6, 0, Math.PI * 2); ctx.fill();
  } else if (featureType === 2) {
    // House — 3D building with walls and roof
    // Walls
    ctx.fillStyle = '#d4a574';
    const bx = cx + sx - 10, by = cy + sy - 8;
    ctx.fillRect(bx, by, 20, 16);
    // Roof (triangle in iso)
    ctx.fillStyle = '#8B4513';
    ctx.beginPath();
    ctx.moveTo(cx + sx - 13, cy + sy - 6);
    ctx.lineTo(cx + sx, cy + sy - 20);
    ctx.lineTo(cx + sx + 13, cy + sy - 6);
    ctx.closePath();
    ctx.fill();
    // Window
    ctx.fillStyle = '#ffee88';
    ctx.fillRect(cx + sx - 3, cy + sy - 4, 6, 5);
    // Door
    ctx.fillStyle = '#5a3a1a';
    ctx.fillRect(cx + sx - 2, cy + sy + 2, 4, 6);
  } else if (featureType === 3) {
    // Industry building
    ctx.fillStyle = '#666';
    const bx = cx + sx - 14, by = cy + sy - 10;
    ctx.fillRect(bx, by, 28, 20);
    // Chimney
    ctx.fillStyle = '#444';
    ctx.fillRect(cx + sx + 6, cy + sy - 22, 6, 14);
    ctx.fillStyle = '#333';
    ctx.fillRect(cx + sx + 5, cy + sy - 24, 8, 4);
    // Door
    ctx.fillStyle = '#222';
    ctx.fillRect(cx + sx - 8, cy + sy + 2, 8, 10);
    // Windows
    ctx.fillStyle = '#8cf';
    ctx.fillRect(cx + sx - 6, cy + sy - 6, 5, 4);
    ctx.fillRect(cx + sx + 2, cy + sy - 6, 5, 4);
  }

  // Outline
  ctx.strokeStyle = 'rgba(0,0,0,0.15)';
  ctx.lineWidth = 0.5;
  ctx.beginPath();
  ctx.moveTo(cx + sx, cy + sy - ISO_H / 2);
  ctx.lineTo(cx + sx + ISO_W / 2, cy + sy);
  ctx.lineTo(cx + sx, cy + sy + ISO_H / 2);
  ctx.lineTo(cx + sx - ISO_W / 2, cy + sy);
  ctx.closePath();
  ctx.stroke();

  tileCache.set(key, canvas);
  return canvas;
}

// ---- Vehicle sprites ----

const vehicleCache = new Map();

function getVehicleSprite(defId) {
  if (vehicleCache.has(defId)) return vehicleCache.get(defId);
  const def = VEHICLE_DEFS[defId];
  if (!def) return null;

  const canvas = document.createElement('canvas');
  canvas.width = 64;
  canvas.height = 48;
  const ctx = canvas.getContext('2d');
  const cx = 32, cy = 24;

  if (def.cls === VEHICLE_CLASSES.TRAIN) {
    // Locomotive body
    ctx.fillStyle = def.color;
    ctx.beginPath();
    ctx.moveTo(cx - 24, cy - 6);
    ctx.lineTo(cx + 24, cy - 6);
    ctx.lineTo(cx + 28, cy);
    ctx.lineTo(cx + 24, cy + 6);
    ctx.lineTo(cx - 24, cy + 6);
    ctx.lineTo(cx - 28, cy);
    ctx.closePath();
    ctx.fill();
    // Cabin
    ctx.fillStyle = shadeColor(def.color, -40);
    ctx.fillRect(cx - 4, cy - 10, 16, 12);
    // Smokestack
    ctx.fillStyle = '#333';
    ctx.fillRect(cx - 16, cy - 12, 6, 8);
    // Wheels
    ctx.fillStyle = '#222';
    ctx.beginPath(); ctx.arc(cx - 18, cy + 8, 5, 0, Math.PI * 2); ctx.fill();
    ctx.beginPath(); ctx.arc(cx + 18, cy + 8, 5, 0, Math.PI * 2); ctx.fill();
  } else if (def.cls === VEHICLE_CLASSES.ROAD) {
    // Bus/Truck body
    ctx.fillStyle = def.color;
    ctx.beginPath();
    ctx.moveTo(cx - 16, cy - 8);
    ctx.lineTo(cx + 16, cy - 8);
    ctx.lineTo(cx + 18, cy);
    ctx.lineTo(cx + 16, cy + 8);
    ctx.lineTo(cx - 16, cy + 8);
    ctx.lineTo(cx - 18, cy);
    ctx.closePath();
    ctx.fill();
    // Windshield
    ctx.fillStyle = '#8cf';
    ctx.fillRect(cx + 6, cy - 6, 8, 6);
    // Wheels
    ctx.fillStyle = '#111';
    ctx.beginPath(); ctx.arc(cx - 10, cy + 10, 4, 0, Math.PI * 2); ctx.fill();
    ctx.beginPath(); ctx.arc(cx + 10, cy + 10, 4, 0, Math.PI * 2); ctx.fill();
  } else if (def.cls === VEHICLE_CLASSES.AIR) {
    // Airplane body
    ctx.fillStyle = def.color;
    ctx.beginPath();
    ctx.ellipse(cx, cy, 20, 6, 0, 0, Math.PI * 2);
    ctx.fill();
    // Wings
    ctx.fillStyle = shadeColor(def.color, -20);
    ctx.beginPath();
    ctx.moveTo(cx - 4, cy - 2);
    ctx.lineTo(cx - 28, cy - 14);
    ctx.lineTo(cx - 28, cy + 14);
    ctx.lineTo(cx - 4, cy + 2);
    ctx.closePath();
    ctx.fill();
    // Tail
    ctx.fillStyle = shadeColor(def.color, -30);
    ctx.fillRect(cx + 16, cy - 10, 8, 4);
  } else if (def.cls === VEHICLE_CLASSES.WATER) {
    // Ship hull
    ctx.fillStyle = def.color;
    ctx.beginPath();
    ctx.moveTo(cx - 24, cy);
    ctx.quadraticCurveTo(cx - 20, cy - 10, cx, cy - 8);
    ctx.quadraticCurveTo(cx + 20, cy - 10, cx + 24, cy);
    ctx.quadraticCurveTo(cx + 20, cy + 10, cx, cy + 8);
    ctx.quadraticCurveTo(cx - 20, cy + 10, cx - 24, cy);
    ctx.closePath();
    ctx.fill();
    // Cabin
    ctx.fillStyle = '#fff';
    ctx.fillRect(cx - 6, cy - 8, 12, 8);
    // Mast
    ctx.fillStyle = '#333';
    ctx.fillRect(cx - 1, cy - 14, 2, 8);
  }

  vehicleCache.set(defId, canvas);
  return canvas;
}

// ---- React Component ----

export default function GameCanvas({ state, onTileClick, onTileHover, onCameraMove, onCameraZoom }) {
  const canvasRef = useRef(null);
  const minimapRef = useRef(null);
  const animFrameRef = useRef(null);
  const dragRef = useRef(null);
  const lastStateRef = useRef(null); // For dirty detection
  const minimapDirtyRef = useRef(true);

  // Compute visible tile range in isometric coords
  const getVisibleRange = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return null;
    const zoom = state.zoom / ISO_W; // normalize zoom to iso tile size
    const hw = canvas.width / 2 / (zoom * ISO_W / 2);
    const hh = canvas.height / 2 / (zoom * ISO_H / 2);
    // In isometric, visible range is roughly diamond-shaped
    const cx = state.cameraX;
    const cy = state.cameraY;
    const range = Math.max(Math.ceil(hw), Math.ceil(hh)) + 2;
    return {
      cx, cy, range,
      x1: Math.max(0, Math.floor(cx - range)),
      y1: Math.max(0, Math.floor(cy - range)),
      x2: Math.min(MAP_SIZE - 1, Math.ceil(cx + range)),
      y2: Math.min(MAP_SIZE - 1, Math.ceil(cy + range)),
    };
  }, [state.cameraX, state.cameraY, state.zoom]);

  // Minimap — only redraw when map data changes
  const drawMinimap = useCallback(() => {
    const minimap = minimapRef.current;
    if (!minimap) return;
    const ctx = minimap.getContext('2d');
    const w = minimap.width;
    const h = minimap.height;

    ctx.fillStyle = '#0a1520';
    ctx.fillRect(0, 0, w, h);

    const scale = w / MAP_SIZE;
    const step = 4;

    for (let y = 0; y < MAP_SIZE; y += step) {
      for (let x = 0; x < MAP_SIZE; x += step) {
        const i = y * MAP_SIZE + x;
        ctx.fillStyle = TERRAIN_COLORS[state.terrain[i]] || '#4a8c3f';
        ctx.fillRect(x * scale, y * scale, scale * step + 1, scale * step + 1);

        if (state.surface[i] === TILE.ROAD) {
          ctx.fillStyle = '#888';
        } else if (state.surface[i] === TILE.RAIL) {
          ctx.fillStyle = '#aaa';
        } else if (state.surface[i] === TILE.STATION) {
          ctx.fillStyle = '#2196F3';
        } else if (state.surface[i] === TILE.AIRPORT) {
          ctx.fillStyle = '#fff';
        } else if (state.surface[i] === TILE.DOCK) {
          ctx.fillStyle = '#8B4513';
        } else {
          continue;
        }
        ctx.fillRect(x * scale, y * scale, scale * step, scale * step);
      }
    }

    for (const town of state.towns) {
      ctx.fillStyle = '#0f0';
      ctx.fillRect(town.x * scale - 2, town.y * scale - 2, 5, 5);
    }
    for (const ind of state.industries) {
      ctx.fillStyle = '#f44';
      ctx.fillRect(ind.x * scale - 2, ind.y * scale - 2, 4, 4);
    }
    for (const v of state.vehicles) {
      const def = VEHICLE_DEFS[v.defId];
      ctx.fillStyle = def?.color || '#fff';
      ctx.fillRect(v.x * scale - 1, v.y * scale - 1, 3, 3);
    }

    const range = getVisibleRange();
    if (range) {
      ctx.strokeStyle = '#fff';
      ctx.lineWidth = 2;
      ctx.strokeRect(
        range.x1 * scale, range.y1 * scale,
        (range.x2 - range.x1 + 1) * scale, (range.y2 - range.y1 + 1) * scale
      );
    }
  }, [state, getVisibleRange]);

  // Main draw — isometric painter's algorithm (back to front)
  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const zoom = state.zoom / ISO_W;

    // Resize if needed
    if (canvas.width !== canvas.clientWidth || canvas.height !== canvas.clientHeight) {
      canvas.width = canvas.clientWidth;
      canvas.height = canvas.clientHeight;
    }

    // Clear
    ctx.fillStyle = '#0a1520';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    const range = getVisibleRange();
    if (!range) return;

    const { cx, cy, x1, y1, x2, y2 } = range;

    // Camera transform for isometric
    const camSx = canvas.width / 2;
    const camSy = canvas.height / 2;
    const baseSx = (cx - cy) * ISO_W / 2 * zoom;
    const baseSy = (cx + cy) * ISO_H / 2 * zoom;

    ctx.save();
    ctx.translate(camSx - baseSx, camSy - baseSy);
    ctx.scale(zoom, zoom);

    // Collect all renderable items and sort by depth
    const renderList = [];

    // Tiles
    for (let y = y1; y <= y2; y++) {
      for (let x = x1; x <= x2; x++) {
        const i = y * MAP_SIZE + x;
        const depth = (x + y); // painter's algorithm sort key
        renderList.push({
          type: 'tile',
          depth,
          x, y,
          terrain: state.terrain[i],
          surface: state.surface[i],
          feature: state.features[i],
          elevation: state.elevation ? state.elevation[i] : 0,
        });
      }
    }

    // Vehicles
    for (const vehicle of state.vehicles) {
      const depth = vehicle.x + vehicle.y;
      renderList.push({
        type: 'vehicle',
        depth,
        vehicle,
      });
    }

    // Sort back to front
    renderList.sort((a, b) => a.depth - b.depth);

    // Draw everything in order
    for (const item of renderList) {
      if (item.type === 'tile') {
        const tile = getIsoTile(item.terrain, item.surface, item.feature, item.elevation);
        const [sx, sy] = isoToScreen(item.x, item.y, item.elevation || 0);
        ctx.drawImage(tile, sx - tile.width / 2, sy - tile.height / 2);
      } else if (item.type === 'vehicle') {
        const v = item.vehicle;
        const def = VEHICLE_DEFS[v.defId];
        if (!def) continue;
        const sprite = getVehicleSprite(v.defId);
        if (!sprite) continue;
        const [sx, sy] = isoToScreen(v.x, v.y, state.elevation ? state.elevation[v.y * MAP_SIZE + v.x] : 0);
        ctx.drawImage(sprite, sx - 32, sy - 24);

        // Selection ring
        if (state.selectedVehicle === v.id) {
          ctx.strokeStyle = '#ff0';
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.arc(sx, sy, 20, 0, Math.PI * 2);
          ctx.stroke();
        }

        // Broken down indicator
        if (v.brokenDown) {
          ctx.fillStyle = '#f00';
          ctx.font = '14px sans-serif';
          ctx.textAlign = 'center';
          ctx.fillText('⚠', sx, sy - 20);
        }

        // Cargo indicator
        if (v.cargo.length > 0) {
          const total = v.cargo.reduce((s, c) => s + c.amount, 0);
          if (total > 0) {
            ctx.fillStyle = '#0f0';
            ctx.font = '10px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText(total.toString(), sx + 16, sy - 12);
          }
        }
      }
    }

    // Hover highlight
    if (state.hoveredTile) {
      const [hx, hy] = isoToScreen(state.hoveredTile.x, state.hoveredTile.y, 0);
      ctx.strokeStyle = '#ff0';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(hx, hy - ISO_H / 2);
      ctx.lineTo(hx + ISO_W / 2, hy);
      ctx.lineTo(hx, hy + ISO_H / 2);
      ctx.lineTo(hx - ISO_W / 2, hy);
      ctx.closePath();
      ctx.stroke();
    }

    // Build preview
    if (state.selectedTool > 1 && state.hoveredTile && !state.routeMode) {
      const [hx, hy] = isoToScreen(state.hoveredTile.x, state.hoveredTile.y, 0);
      ctx.fillStyle = 'rgba(0,255,0,0.25)';
      ctx.beginPath();
      ctx.moveTo(hx, hy - ISO_H / 2);
      ctx.lineTo(hx + ISO_W / 2, hy);
      ctx.lineTo(hx, hy + ISO_H / 2);
      ctx.lineTo(hx - ISO_W / 2, hy);
      ctx.closePath();
      ctx.fill();
    }

    // Route mode highlight — highlight stations
    if (state.routeMode) {
      const allStations = [...(state.stations || []), ...(state.docks || []), ...(state.airports || [])];
      for (const station of allStations) {
        const [sx, sy] = isoToScreen(station.x, station.y, 0);
        ctx.strokeStyle = '#0f0';
        ctx.lineWidth = 2;
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.moveTo(sx, sy - ISO_H / 2 - 4);
        ctx.lineTo(sx + ISO_W / 2 + 4, sy);
        ctx.lineTo(sx, sy + ISO_H / 2 + 4);
        ctx.lineTo(sx - ISO_W / 2 - 4, sy);
        ctx.closePath();
        ctx.stroke();
        ctx.setLineDash([]);
      }
    }

    ctx.restore();

    // Draw minimap (only when dirty)
    drawMinimap();
    minimapDirtyRef.current = false;
  }, [state, getVisibleRange, drawMinimap]);

  // Render loop — only redraw when state actually changes
  useEffect(() => {
    if (lastStateRef.current === state) return; // nothing changed
    lastStateRef.current = state;

    draw();
    minimapDirtyRef.current = true;
  }, [draw]);

  // Continuous render for animations (vehicles moving)
  useEffect(() => {
    let running = true;
    let lastVehicleState = '';
    const loop = () => {
      if (!running) return;
      // Only redraw if vehicles changed position or state
      const currentVState = state.vehicles.map(v => `${v.x},${v.y},${v.state}`).join('|');
      if (currentVState !== lastVehicleState) {
        lastVehicleState = currentVState;
        draw();
      }
      animFrameRef.current = requestAnimationFrame(loop);
    };
    loop();
    return () => { running = false; cancelAnimationFrame(animFrameRef.current); };
  }, [draw, state.vehicles]);

  // Convert screen coords to isometric tile coords
  const screenToTile = useCallback((clientX, clientY) => {
    const canvas = canvasRef.current;
    if (!canvas) return null;
    const rect = canvas.getBoundingClientRect();

    // Mouse position relative to canvas center
    const mx = clientX - rect.left - canvas.width / 2;
    const my = clientY - rect.top - canvas.height / 2;

    // Inverse isometric transform
    const zoom = state.zoom;
    const tileX = Math.floor((mx / (ISO_W / 2) + my / (ISO_H / 2)) / (2 * zoom) + state.cameraX - state.cameraY);
    const tileY = Math.floor((my / (ISO_H / 2) - mx / (ISO_W / 2)) / (2 * zoom) + state.cameraY);

    if (tileX >= 0 && tileX < MAP_SIZE && tileY >= 0 && tileY < MAP_SIZE) {
      return { x: tileX, y: tileY };
    }
    return null;
  }, [state.zoom, state.cameraX, state.cameraY]);

  // Mouse handlers
  const handleMouse = useCallback((e) => {
    const tile = screenToTile(e.clientX, e.clientY);
    if (tile) {
      if (e.type === 'click' && !dragRef.current) onTileClick(tile);
      else if (!dragRef.current) onTileHover(tile);
    }
  }, [screenToTile, onTileClick, onTileHover]);

  // Right-click / middle-click drag to pan
  const handleMouseDown = useCallback((e) => {
    if (e.button === 1 || e.button === 2) {
      e.preventDefault();
      dragRef.current = {
        startX: e.clientX,
        startY: e.clientY,
        startCamX: state.cameraX,
        startCamY: state.cameraY,
      };
    }
  }, [state.cameraX, state.cameraY]);

  const handleMouseMove = useCallback((e) => {
    if (!dragRef.current) {
      handleMouse(e);
      return;
    }
    const dx = (e.clientX - dragRef.current.startX) / (state.zoom / ISO_W) * 0.5;
    const dy = (e.clientY - dragRef.current.startY) / (state.zoom / ISO_H) * 0.5;
    // Convert screen drag to isometric camera movement
    const newCamX = Math.max(0, Math.min(MAP_SIZE - 1, dragRef.current.startCamX - (dx - dy) / 2));
    const newCamY = Math.max(0, Math.min(MAP_SIZE - 1, dragRef.current.startCamY - (dx + dy) / 2));
    if (onCameraMove) onCameraMove({ x: newCamX, y: newCamY });
  }, [state.zoom, onCameraMove, handleMouse]);

  const handleMouseUp = useCallback(() => {
    dragRef.current = null;
  }, []);

  const handleContextMenu = useCallback((e) => e.preventDefault(), []);

  // Scroll wheel zoom
  const handleWheel = useCallback((e) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? -1 : 1;
    onCameraZoom(delta);
  }, [onCameraZoom]);

  // Prevent macOS trackpad pinch-zoom
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const preventGesture = (e) => e.preventDefault();
    canvas.addEventListener('gesturestart', preventGesture, { passive: false });
    canvas.addEventListener('gesturechange', preventGesture, { passive: false });
    return () => {
      canvas.removeEventListener('gesturestart', preventGesture);
      canvas.removeEventListener('gesturechange', preventGesture);
    };
  }, []);

  const handleMinimapClick = useCallback((e) => {
    const minimap = minimapRef.current;
    if (!minimap) return;
    const rect = minimap.getBoundingClientRect();
    const scale = minimap.width / MAP_SIZE;
    const tileX = Math.floor((e.clientX - rect.left) / scale);
    const tileY = Math.floor((e.clientY - rect.top) / scale);
    if (tileX >= 0 && tileX < MAP_SIZE && tileY >= 0 && tileY < MAP_SIZE) {
      onTileClick({ x: tileX, y: tileY, isMinimap: true });
    }
  }, [onTileClick]);

  return (
    <>
      <div className="canvas-container">
        <canvas ref={canvasRef} className="game-canvas"
          onClick={handleMouse}
          onMouseMove={handleMouseMove}
          onMouseDown={handleMouseDown}
          onMouseUp={handleMouseUp}
          onContextMenu={handleContextMenu}
          onWheel={handleWheel} />
      </div>
      <div className="minimap-container">
        <canvas ref={minimapRef} className="minimap-canvas"
          width={180} height={180} onClick={handleMinimapClick} />
      </div>
    </>
  );
}
