// ===== CANVAS RENDERER =====

import { useRef, useEffect, useCallback } from 'react';
import {
  MAP_SIZE, TILE_SIZE, TERRAIN, TERRAIN_COLORS, TILE, SURFACE_COLORS,
  VEHICLE_DEFS, VEHICLE_CLASSES
} from '../game/constants.js';

// Pre-rendered tile cache
const tileCache = new Map();

function getTileCanvas(terrainType, surfaceType, featureType) {
  const key = `${terrainType}_${surfaceType}_${featureType}`;
  if (tileCache.has(key)) return tileCache.get(key);

  const size = TILE_SIZE * 4;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');

  // Base terrain
  ctx.fillStyle = TERRAIN_COLORS[terrainType] || '#4a8c3f';
  ctx.fillRect(0, 0, size, size);

  // Terrain detail
  if (terrainType === TERRAIN.WATER) {
    ctx.fillStyle = 'rgba(100,180,255,0.15)';
    ctx.fillRect(0, size * 0.3, size, 2);
    ctx.fillRect(0, size * 0.7, size, 2);
  } else if (terrainType === TERRAIN.GRASS) {
    ctx.fillStyle = 'rgba(0,80,0,0.2)';
    ctx.fillRect(size * 0.2, size * 0.3, 2, 3);
    ctx.fillRect(size * 0.6, size * 0.7, 2, 3);
  } else if (terrainType === TERRAIN.DESERT) {
    ctx.fillStyle = 'rgba(200,180,100,0.3)';
    ctx.fillRect(size * 0.3, size * 0.5, 3, 2);
    ctx.fillRect(size * 0.7, size * 0.2, 3, 2);
  } else if (terrainType === TERRAIN.MOUNTAIN) {
    ctx.fillStyle = 'rgba(0,0,0,0.3)';
    ctx.beginPath();
    ctx.moveTo(size * 0.2, size);
    ctx.lineTo(size * 0.5, size * 0.2);
    ctx.lineTo(size * 0.8, size);
    ctx.fill();
  }

  // Surface overlay
  if (surfaceType === TILE.ROAD) {
    ctx.fillStyle = '#444';
    ctx.fillRect(0, size / 2 - size * 0.15, size, size * 0.3);
    ctx.fillRect(size / 2 - size * 0.15, 0, size * 0.3, size);
    ctx.fillStyle = '#cc4';
    ctx.fillRect(size / 2 - 1, 0, 2, size * 0.4);
    ctx.fillRect(size / 2 - 1, size * 0.6, 2, size * 0.4);
  } else if (surfaceType === TILE.RAIL) {
    ctx.fillStyle = '#3a2a1a';
    ctx.fillRect(size * 0.3, 0, size * 0.4, size);
    ctx.fillStyle = '#aaa';
    ctx.fillRect(size * 0.35, 0, 2, size);
    ctx.fillRect(size * 0.6, 0, 2, size);
    ctx.fillStyle = '#6b4226';
    for (let y = 0; y < size; y += 6) ctx.fillRect(size * 0.32, y, size * 0.36, 3);
  } else if (surfaceType === TILE.STATION) {
    ctx.fillStyle = '#1565C0';
    ctx.fillRect(0, 0, size, size);
    ctx.fillStyle = '#1976D2';
    ctx.fillRect(2, 2, size - 4, size - 4);
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, size * 0.1, size, 3);
    ctx.fillRect(0, size * 0.85, size, 3);
  } else if (surfaceType === TILE.BUS_STOP) {
    ctx.fillStyle = '#E65100';
    ctx.fillRect(size / 2 - 3, 0, 6, size);
    ctx.fillStyle = '#fff';
    ctx.fillRect(size / 2 - 2, size * 0.3, 4, size * 0.4);
  } else if (surfaceType === TILE.TRUCK_STOP) {
    ctx.fillStyle = '#8B6914';
    ctx.fillRect(size / 2 - 4, 0, 8, size);
  } else if (surfaceType === TILE.AIRPORT) {
    ctx.fillStyle = '#555';
    ctx.fillRect(0, 0, size, size);
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, size / 2 - 2, size, 4);
    ctx.fillRect(size / 2 - 2, 0, 4, size);
  } else if (surfaceType === TILE.DOCK) {
    ctx.fillStyle = '#5D3A1A';
    ctx.fillRect(0, 0, size, size);
    ctx.fillStyle = '#8B6914';
    ctx.fillRect(0, 0, size, size * 0.3);
    ctx.fillStyle = '#333';
    ctx.fillRect(size * 0.2, size * 0.1, 4, 4);
    ctx.fillRect(size * 0.7, size * 0.1, 4, 4);
  } else if (surfaceType === TILE.BRIDGE) {
    ctx.fillStyle = '#777';
    ctx.fillRect(0, 0, size, size);
    ctx.fillStyle = '#999';
    ctx.fillRect(size * 0.2, 0, size * 0.6, size);
  } else if (surfaceType === TILE.SIGNAL) {
    ctx.fillStyle = '#c00';
    ctx.fillRect(size / 2 - 3, size * 0.2, 6, size * 0.6);
    ctx.fillStyle = '#ff0';
    ctx.beginPath();
    ctx.arc(size / 2, size / 2, 4, 0, Math.PI * 2);
    ctx.fill();
  }

  // Features
  if (featureType === 1) {
    ctx.fillStyle = '#2d5a1e';
    ctx.beginPath(); ctx.arc(size / 2, size / 2 - 4, size * 0.35, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = '#1a3a10';
    ctx.beginPath(); ctx.arc(size / 2 - 3, size / 2 - 6, size * 0.25, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = '#4a2a0a';
    ctx.fillRect(size / 2 - 2, size / 2, 4, size * 0.3);
  } else if (featureType === 2) {
    ctx.fillStyle = '#d4a574';
    ctx.fillRect(size * 0.25, size * 0.3, size * 0.5, size * 0.5);
    ctx.fillStyle = '#8B4513';
    ctx.beginPath();
    ctx.moveTo(size * 0.2, size * 0.3);
    ctx.lineTo(size * 0.5, size * 0.1);
    ctx.lineTo(size * 0.8, size * 0.3);
    ctx.fill();
    ctx.fillStyle = '#ff8';
    ctx.fillRect(size * 0.4, size * 0.4, size * 0.2, size * 0.2);
  } else if (featureType === 3) {
    ctx.fillStyle = '#555';
    ctx.fillRect(size * 0.15, size * 0.25, size * 0.7, size * 0.55);
    ctx.fillStyle = '#333';
    ctx.fillRect(size * 0.6, size * 0.1, size * 0.15, size * 0.3);
    ctx.fillStyle = '#222';
    ctx.fillRect(size * 0.4, size * 0.55, size * 0.2, size * 0.25);
  }

  tileCache.set(key, canvas);
  return canvas;
}

// ---- React Component ----

export default function GameCanvas({ state, onTileClick, onTileHover, onCameraMove }) {
  const canvasRef = useRef(null);
  const minimapRef = useRef(null);
  const animFrameRef = useRef(null);
  const dragRef = useRef(null); // { startX, startY, startCamX, startCamY }

  const getVisibleRange = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return null;
    const ts = state.zoom;
    const w = canvas.width / ts;
    const h = canvas.height / ts;
    return {
      x1: Math.max(0, Math.floor(state.cameraX - w / 2)),
      y1: Math.max(0, Math.floor(state.cameraY - h / 2)),
      x2: Math.min(MAP_SIZE - 1, Math.ceil(state.cameraX + w / 2)),
      y2: Math.min(MAP_SIZE - 1, Math.ceil(state.cameraY + h / 2)),
    };
  }, [state.cameraX, state.cameraY, state.zoom]);

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

    // Towns
    for (const town of state.towns) {
      ctx.fillStyle = '#0f0';
      ctx.fillRect(town.x * scale - 2, town.y * scale - 2, 5, 5);
    }

    // Industries
    for (const ind of state.industries) {
      ctx.fillStyle = '#f44';
      ctx.fillRect(ind.x * scale - 2, ind.y * scale - 2, 4, 4);
    }

    // Vehicles
    for (const v of state.vehicles) {
      const def = VEHICLE_DEFS[v.defId];
      ctx.fillStyle = def?.color || '#fff';
      ctx.fillRect(v.x * scale - 1, v.y * scale - 1, 3, 3);
    }

    // Camera viewport
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

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const ts = state.zoom;

    if (canvas.width !== canvas.clientWidth || canvas.height !== canvas.clientHeight) {
      canvas.width = canvas.clientWidth;
      canvas.height = canvas.clientHeight;
    }

    ctx.fillStyle = '#0a1520';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    const range = getVisibleRange();
    if (!range) return;

    const offsetX = canvas.width / 2 - state.cameraX * ts;
    const offsetY = canvas.height / 2 - state.cameraY * ts;

    // Draw tiles
    for (let y = range.y1; y <= range.y2; y++) {
      for (let x = range.x1; x <= range.x2; x++) {
        const i = y * MAP_SIZE + x;
        const tc = getTileCanvas(state.terrain[i], state.surface[i], state.features[i]);
        ctx.drawImage(tc, Math.floor(x * ts + offsetX), Math.floor(y * ts + offsetY), ts, ts);
      }
    }

    // Draw vehicles
    for (const vehicle of state.vehicles) {
      const def = VEHICLE_DEFS[vehicle.defId];
      if (!def) continue;
      const px = vehicle.x * ts + offsetX;
      const py = vehicle.y * ts + offsetY;
      ctx.save();
      ctx.translate(px + ts / 2, py + ts / 2);

      if (def.cls === VEHICLE_CLASSES.TRAIN) {
        ctx.fillStyle = def.color;
        ctx.fillRect(-ts * 0.4, -ts * 0.15, ts * 0.8, ts * 0.3);
        ctx.fillStyle = '#333';
        ctx.fillRect(-ts * 0.1, -ts * 0.2, ts * 0.2, ts * 0.4);
        ctx.fillStyle = '#222';
        ctx.beginPath();
        ctx.arc(-ts * 0.25, ts * 0.15, ts * 0.08, 0, Math.PI * 2);
        ctx.arc(ts * 0.25, ts * 0.15, ts * 0.08, 0, Math.PI * 2);
        ctx.fill();
      } else if (def.cls === VEHICLE_CLASSES.ROAD) {
        ctx.fillStyle = def.color;
        ctx.fillRect(-ts * 0.25, -ts * 0.2, ts * 0.5, ts * 0.4);
        ctx.fillStyle = '#333';
        ctx.fillRect(-ts * 0.25, -ts * 0.2, ts * 0.5, ts * 0.08);
        ctx.fillStyle = '#111';
        ctx.beginPath();
        ctx.arc(-ts * 0.15, ts * 0.2, ts * 0.06, 0, Math.PI * 2);
        ctx.arc(ts * 0.15, ts * 0.2, ts * 0.06, 0, Math.PI * 2);
        ctx.fill();
      } else if (def.cls === VEHICLE_CLASSES.AIR) {
        ctx.fillStyle = def.color;
        ctx.beginPath();
        ctx.moveTo(0, -ts * 0.4);
        ctx.lineTo(ts * 0.3, 0);
        ctx.lineTo(0, ts * 0.4);
        ctx.lineTo(-ts * 0.3, 0);
        ctx.fill();
        ctx.fillStyle = '#aaa';
        ctx.fillRect(-ts * 0.3, -ts * 0.05, ts * 0.6, ts * 0.1);
      } else if (def.cls === VEHICLE_CLASSES.WATER) {
        ctx.fillStyle = def.color;
        ctx.beginPath();
        ctx.moveTo(-ts * 0.35, 0);
        ctx.lineTo(0, -ts * 0.3);
        ctx.lineTo(ts * 0.35, 0);
        ctx.lineTo(0, ts * 0.3);
        ctx.fill();
        ctx.fillStyle = '#fff';
        ctx.fillRect(-ts * 0.08, -ts * 0.08, ts * 0.16, ts * 0.16);
      }

      // Cargo indicator
      if (vehicle.cargo.length > 0) {
        const total = vehicle.cargo.reduce((s, c) => s + c.amount, 0);
        if (total > 0) {
          ctx.fillStyle = '#0f0';
          ctx.fillRect(ts * 0.2, -ts * 0.35, ts * 0.1, ts * 0.1);
        }
      }

      if (vehicle.brokenDown) {
        ctx.fillStyle = '#f00';
        ctx.font = `${ts * 0.5}px sans-serif`;
        ctx.textAlign = 'center';
        ctx.fillText('⚠', 0, -ts * 0.3);
      }

      if (state.selectedVehicle === vehicle.id) {
        ctx.strokeStyle = '#ff0';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(0, 0, ts * 0.6, 0, Math.PI * 2);
        ctx.stroke();
      }

      ctx.restore();
    }

    // Hover highlight
    if (state.hoveredTile) {
      const hx = Math.floor(state.hoveredTile.x * ts + offsetX);
      const hy = Math.floor(state.hoveredTile.y * ts + offsetY);
      ctx.strokeStyle = '#ff0';
      ctx.lineWidth = 2;
      ctx.strokeRect(hx, hy, ts, ts);
    }

    // Build preview
    if (state.selectedTool > 1 && state.hoveredTile) {
      const hx = state.hoveredTile.x * ts + offsetX;
      const hy = state.hoveredTile.y * ts + offsetY;
      ctx.fillStyle = 'rgba(0,255,0,0.3)';
      ctx.fillRect(hx, hy, ts, ts);
    }

    // Grid
    ctx.strokeStyle = 'rgba(255,255,255,0.03)';
    ctx.lineWidth = 1;
    for (let x = range.x1; x <= range.x2; x++) {
      const px = Math.floor(x * ts + offsetX);
      ctx.beginPath(); ctx.moveTo(px, 0); ctx.lineTo(px, canvas.height); ctx.stroke();
    }
    for (let y = range.y1; y <= range.y2; y++) {
      const py = Math.floor(y * ts + offsetY);
      ctx.beginPath(); ctx.moveTo(0, py); ctx.lineTo(canvas.width, py); ctx.stroke();
    }

    // Draw minimap
    drawMinimap();
  }, [state, getVisibleRange, drawMinimap]);

  // Render loop
  useEffect(() => {
    let running = true;
    const loop = () => {
      if (!running) return;
      draw();
      animFrameRef.current = requestAnimationFrame(loop);
    };
    loop();
    return () => { running = false; cancelAnimationFrame(animFrameRef.current); };
  }, [draw]);

  // Mouse handlers
  const handleMouse = useCallback((e) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const ts = state.zoom;
    const offsetX = canvas.width / 2 - state.cameraX * ts;
    const offsetY = canvas.height / 2 - state.cameraY * ts;
    const tileX = Math.floor((e.clientX - rect.left - offsetX) / ts);
    const tileY = Math.floor((e.clientY - rect.top - offsetY) / ts);

    if (tileX >= 0 && tileX < MAP_SIZE && tileY >= 0 && tileY < MAP_SIZE) {
      const tile = { x: tileX, y: tileY };
      if (e.type === 'click' && !dragRef.current) onTileClick(tile);
      else if (!dragRef.current) onTileHover(tile);
    }
  }, [state.zoom, state.cameraX, state.cameraY, onTileClick, onTileHover]);

  // Right-click / middle-click drag to pan
  const handleMouseDown = useCallback((e) => {
    if (e.button === 1 || e.button === 2) { // middle or right click
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
      // Still update hover
      handleMouse(e);
      return;
    }
    const dx = (e.clientX - dragRef.current.startX) / state.zoom;
    const dy = (e.clientY - dragRef.current.startY) / state.zoom;
    const newCamX = Math.max(0, Math.min(MAP_SIZE - 1, dragRef.current.startCamX - dx));
    const newCamY = Math.max(0, Math.min(MAP_SIZE - 1, dragRef.current.startCamY - dy));
    if (onCameraMove) onCameraMove({ x: newCamX, y: newCamY });
  }, [state.zoom, onCameraMove, handleMouse]);

  const handleMouseUp = useCallback(() => {
    dragRef.current = null;
  }, []);

  const handleContextMenu = useCallback((e) => e.preventDefault(), []);

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
          onClick={handleMouse} onMouseMove={handleMouse} />
      </div>
      <div className="minimap-container">
        <canvas ref={minimapRef} className="minimap-canvas"
          width={180} height={180} onClick={handleMinimapClick} />
      </div>
    </>
  );
}
