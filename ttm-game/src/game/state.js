// ===== GAME STATE & ACTIONS =====

import {
  MAP_SIZE, TERRAIN, TILE, CARGO_TYPES, INDUSTRY_TYPES,
  VEHICLE_DEFS, VEHICLE_CLASSES, TOWN_SIZES, TOOLS,
  STARTING_MONEY, MAX_LOAN, LOAN_STEP, INTEREST_RATE,
  START_YEAR, END_YEAR, GAME_SPEED, BUILD_COSTS,
  STATION_SIZES, DIFFICULTY, FARE_PER_TILE, DAYS_PER_MONTH
} from './constants.js';
import { generateMap, findFlatArea, findWaterEdge, generateTownName } from './terrain.js';

// ---- Create new game ----

let nextStationId = 0;

export function createNewGame(seed = 42, difficulty = 'normal') {
  nextStationId = 0;
  const diff = DIFFICULTY[difficulty] || DIFFICULTY.normal;
  const mapData = generateMap(seed);

  const terrain = mapData.terrain;
  const features = mapData.features;
  const elevation = mapData.elevation;
  const surface = new Uint8Array(MAP_SIZE * MAP_SIZE);
  const stationMap = new Uint8Array(MAP_SIZE * MAP_SIZE);

  // RNG helper
  let rng = seed + 5000;
  const rngNext = () => { rng = (rng * 16807) % 2147483647; return rng; };

  // ---- Place towns ----
  const towns = [];
  const townNames = ['Springfield','Riverside','Lakewood','Fairview','Oakdale','Maplewood','Cedarburg','Brookfield'];
  for (let i = 0; i < 6; i++) {
    const loc = findFlatArea(terrain, MAP_SIZE, -0.05, 0.15, rngNext() + i * 1000);
    if (!loc) continue;

    // Mark town tiles
    for (let dy = -6; dy <= 6; dy++) {
      for (let dx = -6; dx <= 6; dx++) {
        if (dx * dx + dy * dy > 36) continue;
        const idx = (loc.y + dy) * MAP_SIZE + (loc.x + dx);
        if (terrain[idx] === TERRAIN.GRASS || terrain[idx] === TERRAIN.DESERT) {
          features[idx] = 2; // house
        }
      }
    }

    // Build internal roads
    for (let dy = -4; dy <= 4; dy += 3) {
      for (let dx = -4; dx <= 4; dx++) {
        const idx = (loc.y + dy) * MAP_SIZE + (loc.x + dx);
        if (terrain[idx] !== TERRAIN.WATER) surface[idx] = TILE.ROAD;
      }
    }
    for (let dx = -4; dx <= 4; dx += 3) {
      for (let dy = -4; dy <= 4; dy++) {
        const idx = (loc.y + dy) * MAP_SIZE + (loc.x + dx);
        if (terrain[idx] !== TERRAIN.WATER) surface[idx] = TILE.ROAD;
      }
    }

    const pop = 40 + (rngNext() % 60);
    towns.push({
      id: towns.length,
      name: townNames[i] || `Town ${i}`,
      x: loc.x, y: loc.y,
      population: pop,
      passengersWaiting: 0,
      mailWaiting: 0,
      serviceRating: 50,
      growthTimer: 0,
    });
  }

  // ---- Place industries ----
  const industries = [];
  const availableInd = INDUSTRY_TYPES.filter(ind => ind.minYear <= START_YEAR);
  for (let i = 0; i < Math.min(8, availableInd.length); i++) {
    const loc = findFlatArea(terrain, MAP_SIZE, -0.02, 0.18, rngNext() + i * 2000 + 50000);
    if (!loc) continue;

    // Check distance from towns
    let tooClose = false;
    for (const t of towns) {
      if (Math.hypot(t.x - loc.x, t.y - loc.y) < 35) { tooClose = true; break; }
    }
    if (tooClose) continue;

    const indDef = availableInd[i % availableInd.length];
    const industry = {
      id: industries.length,
      type: indDef.id,
      name: indDef.name,
      x: loc.x, y: loc.y,
      producesCargoId: indDef.producesCargoId,
      consumesCargoId: indDef.consumesCargoId ?? null,
      storage: 0,
      maxStorage: 100,
      productionRate: 2 + (rngNext() % 3),
      active: true,
      connected: false,
      needsCargo: indDef.consumesCargoId !== null ? {} : null,
    };

    // Mark industry tiles
    for (let dy = -3; dy <= 3; dy++) {
      for (let dx = -3; dx <= 3; dx++) {
        const idx = (loc.y + dy) * MAP_SIZE + (loc.x + dx);
        if (terrain[idx] !== TERRAIN.WATER) {
          features[idx] = 3; // industry
        }
      }
    }

    // Build a road leading to it
    const roadDir = rngNext() % 4;
    for (let d = 4; d < 20; d++) {
      let rx = loc.x + [d, -d, 0, 0][roadDir];
      let ry = loc.y + [0, 0, d, -d][roadDir];
      if (rx < 0 || rx >= MAP_SIZE || ry < 0 || ry >= MAP_SIZE) break;
      const idx = ry * MAP_SIZE + rx;
      if (terrain[idx] === TERRAIN.WATER) break;
      surface[idx] = TILE.ROAD;
    }

    industries.push(industry);
  }

  // ---- Place docks ----
  const docks = [];
  for (let i = 0; i < 3; i++) {
    const loc = findWaterEdge(terrain, MAP_SIZE, rngNext() + i * 3000 + 100000);
    if (loc) {
      const idx = loc.y * MAP_SIZE + loc.x;
      surface[idx] = TILE.DOCK;
      // Also mark adjacent land tile
      const landIdx = loc.y * MAP_SIZE + loc.x + 1;
      if (landIdx < terrain.length && terrain[landIdx] !== TERRAIN.WATER) {
        surface[landIdx] = TILE.ROAD;
      }
      stationMap[idx] = nextStationId;
      stationMap[landIdx] = nextStationId;
      docks.push({ id: nextStationId - 1, x: loc.x, y: loc.y });
      nextStationId++;
    }
  }

  // ---- Starting money ----
  const money = Math.floor(diff.money);

  // Camera starts near first town
  const camX = towns.length > 0 ? towns[0].x : MAP_SIZE / 2;
  const camY = towns.length > 0 ? towns[0].y : MAP_SIZE / 2;

  return {
    // Map data
    terrain,
    features,
    surface,
    stationMap,

    // Locations
    towns,
    industries,
    docks,
    airports: [],
    stations: [], // train stations, bus stops, truck stops
    nextStationId,

    // Vehicles
    vehicles: [],
    nextVehicleId: 0,

    // Economy
    money,
    loan: 0,
    maxLoan: diff.maxLoan,
    interestRate: diff.interest,
    targetWealth: diff.target,
    costMult: diff.costMult,
    monthlyIncome: 0,
    monthlyExpenses: 0,
    monthlyProfit: [], // last 24 months of profit

    // Game time
    date: new Date(START_YEAR, 0, 1),
    dateTicks: 0,
    gameSpeed: GAME_SPEED.NORMAL,
    paused: false,

    // Player state
    selectedTool: TOOLS.CURSOR,
    buildMode: null,
    cameraX: camX,
    cameraY: camY,
    zoom: 3,
    selectedVehicle: null,
    hoveredTile: null,

    // Stats
    totalPassengers: 0,
    totalCargo: 0,
    reputation: 50,

    // UI state (not saved)
    showPanel: null,
    notifications: [],
    difficulty,
  };
}

// ---- Game Actions ----
export const ACTIONS = {
  TICK: 'TICK',
  BUILD: 'BUILD',
  DEMOLISH: 'DEMOLISH',
  BUY_VEHICLE: 'BUY_VEHICLE',
  SCRAP_VEHICLE: 'SCRAP_VEHICLE',
  CHANGE_TOOL: 'CHANGE_TOOL',
  CHANGE_SPEED: 'CHANGE_SPEED',
  TOGGLE_PAUSE: 'TOGGLE_PAUSE',
  MOVE_CAMERA: 'MOVE_CAMERA',
  ZOOM: 'ZOOM',
  TAKE_LOAN: 'TAKE_LOAN',
  REPAY_LOAN: 'REPAY_LOAN',
  SHOW_PANEL: 'SHOW_PANEL',
  HIDE_PANEL: 'HIDE_PANEL',
  SELECT_VEHICLE: 'SELECT_VEHICLE',
  SET_VEHICLE_ROUTE: 'SET_VEHICLE_ROUTE',
  LOAD_GAME: 'LOAD_GAME',
  NEW_GAME: 'NEW_GAME',
  CLEAR_NOTIFICATIONS: 'CLEAR_NOTIFICATIONS',
};

// ---- Pathfinding (BFS) ----
export function findPath(surface, terrain, startX, startY, endX, endY, requiredSurface, maxDist = 500) {
  if (startX === endX && startY === endY) return [];
  if (startX < 0 || startX >= MAP_SIZE || startY < 0 || startY >= MAP_SIZE) return null;
  if (endX < 0 || endX >= MAP_SIZE || endY < 0 || endY >= MAP_SIZE) return null;

  const startIdx = startY * MAP_SIZE + startX;
  if (surface[startIdx] !== requiredSurface && surface[startIdx] !== TILE.STATION) return null;

  const visited = new Uint8Array(MAP_SIZE * MAP_SIZE);
  const parentX = new Int16Array(MAP_SIZE * MAP_SIZE);
  const parentY = new Int16Array(MAP_SIZE * MAP_SIZE);
  const queue = [startX, startY, 0]; // x, y, dist flattened
  let head = 0;
  visited[startIdx] = 1;

  const dirs = [0, 1, 0, -1, 0]; // right, down, left, up flattened
  let found = false;
  let endDist = maxDist;

  while (head < queue.length) {
    const cx = queue[head]; head++;
    const cy = queue[head]; head++;
    const cDist = queue[head]; head++;
    if (cDist > maxDist) break;

    if (cx === endX && cy === endY) { found = true; endDist = cDist; break; }

    for (let d = 0; d < 4; d++) {
      const nx = cx + dirs[d * 2];
      const ny = cy + dirs[d * 2 + 1];
      if (nx < 0 || nx >= MAP_SIZE || ny < 0 || ny >= MAP_SIZE) continue;
      const nIdx = ny * MAP_SIZE + nx;
      if (visited[nIdx]) continue;
      if (terrain[nIdx] === TERRAIN.WATER) continue;

      const s = surface[nIdx];
      const canPass = s === requiredSurface || s === TILE.STATION || s === TILE.SIGNAL;
      if (!canPass) continue;

      visited[nIdx] = 1;
      parentX[nIdx] = cx;
      parentY[nIdx] = cy;
      queue.push(nx, ny, cDist + 1);
    }
  }

  if (!found) return null;

  // Reconstruct path
  const path = [];
  let cx = endX, cy = endY;
  let steps = 0;
  while ((cx !== startX || cy !== startY) && steps < maxDist + 1) {
    path.unshift({ x: cx, y: cy });
    const idx = cy * MAP_SIZE + cx;
    const px = parentX[idx];
    const py = parentY[idx];
    if (px === 0 && py === 0 && cx !== startX || cy !== startY) {
      // Reached start or no parent
      if (cx === startX && cy === startY) break;
      if (px === 0 && py === 0) break;
    }
    cx = px; cy = py;
    steps++;
  }
  return path;
}

// ---- Station helpers ----

function getStationAt(stationMap, x, y) {
  if (x < 0 || x >= MAP_SIZE || y < 0 || y >= MAP_SIZE) return null;
  const id = stationMap[y * MAP_SIZE + x];
  return id > 0 ? id - 1 : null;
}

export function getStation(state, id) {
  // Check all station types
  for (const s of state.stations) if (s.id === id) return s;
  for (const d of state.docks) if (d.id === id) return d;
  for (const a of state.airports) if (a.id === id) return a;
  return null;
}

export function getStationAtPos(state, x, y) {
  const id = getStationAt(state.stationMap, x, y);
  if (id === null) return null;
  return getStation(state, id);
}

// ---- Build a station ----

export function buildStation(state, tool, x, y) {
  const size = STATION_SIZES[tool];
  if (!size) return state;

  // Check bounds
  const hx = Math.floor(size / 2);
  if (x - hx < 0 || x + hx >= MAP_SIZE || y - hx < 0 || y + hx >= MAP_SIZE) return state;

  // Check if airport (square) or linear
  const isAirport = tool === TOOLS.BUILD_AIRPORT;
  const surfaceType = tool === TOOLS.BUILD_STATION ? TILE.STATION :
                      tool === TOOLS.BUILD_BUS_STOP ? TILE.BUS_STOP :
                      tool === TOOLS.BUILD_TRUCK_STOP ? TILE.TRUCK_STOP :
                      tool === TOOLS.BUILD_AIRPORT ? TILE.AIRPORT :
                      tool === TOOLS.BUILD_DOCK ? TILE.DOCK : TILE.NONE;

  if (surfaceType === TILE.NONE) return state;

  // Check if we can build
  let canBuild = true;
  let tiles = [];
  for (let dy = isAirport ? -hx : 0; dy <= (isAirport ? hx : 0); dy++) {
    for (let dx = -hx; dx <= hx; dx++) {
      const tx = x + dx;
      const ty = y + dy;
      if (tx < 0 || tx >= MAP_SIZE || ty < 0 || ty >= MAP_SIZE) { canBuild = false; break; }
      const idx = ty * MAP_SIZE + tx;
      if (state.surface[idx] !== TILE.NONE && state.surface[idx] !== TILE.ROAD) { canBuild = false; break; }
      if (tool === TOOLS.BUILD_DOCK && state.terrain[idx] !== TERRAIN.WATER) { canBuild = false; break; }
      if (tool !== TOOLS.BUILD_DOCK && state.terrain[idx] === TERRAIN.WATER) { canBuild = false; break; }
      tiles.push(idx);
    }
  }
  if (!canBuild) return state;

  // Check cost
  const cost = Math.floor(BUILD_COSTS[tool] * state.costMult);
  if (state.money < cost) return state;

  const newState = { ...state };
  const newTerrain = newState.terrain;
  const newSurface = new Uint8Array(newState.surface);
  const newFeatures = new Uint8Array(newState.features);
  const newStationMap = new Uint8Array(newState.stationMap);
  const stationId = newState.nextStationId;

  // Place station tiles
  for (const idx of tiles) {
    newSurface[idx] = surfaceType;
    newStationMap[idx] = stationId;
    newFeatures[idx] = 0; // clear trees/houses
  }

  // Create station object
  const station = {
    id: stationId,
    type: surfaceType,
    tool,
    x, y,
    name: `${TOOLS[tool]?.replace('BUILD_', '').replace(/_/g,' ') || 'Station'} ${stationId}`,
    waitingPassengers: 0,
    waitingMail: 0,
    waitingCargo: {},
  };

  const newStations = [...newState.stations, station];

  return {
    ...newState,
    terrain: newTerrain,
    surface: newSurface,
    features: newFeatures,
    stationMap: newStationMap,
    stations: newStations,
    nextStationId: stationId + 1,
    money: newState.money - cost,
    notifications: [...newState.notifications, `Built ${station.name} (-$${cost})`],
  };
}

// ---- Buy a vehicle ----

export function buyVehicle(state, vehicleDefId, stationId) {
  const def = VEHICLE_DEFS[vehicleDefId];
  if (!def) return state;

  // Check if available this year
  const currentYear = state.date.getFullYear();
  if (def.minYear > currentYear) return state;

  const cost = Math.floor(def.cost * state.costMult);
  if (state.money < cost) return state;

  const station = getStation(state, stationId);
  if (!station) return state;

  const vehicle = {
    id: state.nextVehicleId,
    defId: vehicleDefId,
    stationId,
    x: station.x,
    y: station.y,
    cargo: [],
    route: [], // array of station IDs
    routeIndex: -1,
    state: 'idle', // idle, moving, loading, unloading
    speed: def.speed,
    reliability: def.reliability,
    brokenDown: false,
    breakdownTimer: 0,
    tileProgress: 0, // sub-tile position for smooth movement
  };

  return {
    ...state,
    vehicles: [...state.vehicles, vehicle],
    nextVehicleId: state.nextVehicleId + 1,
    money: state.money - cost,
    notifications: [...state.notifications, `Bought ${def.name} (-$${cost})`],
  };
}

// ---- Set vehicle route ----

export function setVehicleRoute(state, vehicleId, route) {
  const newVehicles = state.vehicles.map(v => {
    if (v.id === vehicleId) {
      return { ...v, route, routeIndex: -1, state: 'idle' };
    }
    return v;
  });
  return { ...state, vehicles: newVehicles };
}

// ---- Scraps a vehicle ----

export function scrapVehicle(state, vehicleId) {
  const vehicle = state.vehicles.find(v => v.id === vehicleId);
  if (!vehicle) return state;
  const def = VEHICLE_DEFS[vehicle.defId];
  const scrapValue = Math.floor(def.cost * 0.2);
  return {
    ...state,
    vehicles: state.vehicles.filter(v => v.id !== vehicleId),
    money: state.money + scrapValue,
    notifications: [...state.notifications, `Scrapped ${def.name} (+$${scrapValue})`],
  };
}
