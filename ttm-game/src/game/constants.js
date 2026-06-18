// ===== TRANSPORT TYCOON REMAKE - CONSTANTS =====

// Map configuration
export const MAP_SIZE = 1024;
export const TILE_SIZE = 8;

// Terrain types
export const TERRAIN = {
  GRASS: 0,
  WATER: 1,
  HILLS: 2,
  MOUNTAIN: 3,
  DESERT: 4,
  SNOW: 5,
  TUNDRA: 6,
};

export const TERRAIN_COLORS = {
  [TERRAIN.GRASS]: '#4a8c3f',
  [TERRAIN.WATER]: '#2e6b9e',
  [TERRAIN.HILLS]: '#5a9c4f',
  [TERRAIN.MOUNTAIN]: '#8a8a8a',
  [TERRAIN.DESERT]: '#c4a44a',
  [TERRAIN.SNOW]: '#e8e8f0',
  [TERRAIN.TUNDRA]: '#b8c8d8',
};

export const TERRAIN_NAMES = {
  [TERRAIN.GRASS]: 'Grassland',
  [TERRAIN.WATER]: 'Water',
  [TERRAIN.HILLS]: 'Hills',
  [TERRAIN.MOUNTAIN]: 'Mountain',
  [TERRAIN.DESERT]: 'Desert',
  [TERRAIN.SNOW]: 'Snow',
  [TERRAIN.TUNDRA]: 'Tundra',
};

// Surface types (built infrastructure)
export const TILE = {
  NONE: 0,
  ROAD: 1,
  RAIL: 2,
  STATION: 3,
  BUS_STOP: 4,
  TRUCK_STOP: 5,
  AIRPORT: 6,
  DOCK: 7,
  BRIDGE: 8,
  TUNNEL: 9,
  SIGNAL: 10,
};

export const SURFACE_COLORS = {
  [TILE.NONE]: null,
  [TILE.ROAD]: '#555555',
  [TILE.RAIL]: '#4a3728',
  [TILE.STATION]: '#2196F3',
  [TILE.BUS_STOP]: '#FF9800',
  [TILE.TRUCK_STOP]: '#b8860b',
  [TILE.AIRPORT]: '#666666',
  [TILE.DOCK]: '#8B4513',
  [TILE.BRIDGE]: '#999999',
  [TILE.TUNNEL]: '#444444',
  [TILE.SIGNAL]: '#ff0000',
};

// Feature types (objects on tiles)
export const FEATURE = {
  NONE: 0,
  TREE: 1,
  HOUSE: 2,
  INDUSTRY: 3,
};

// Tool / Build mode
export const TOOLS = {
  CURSOR: 0,
  DEMOLISH: 1,
  BUILD_ROAD: 2,
  BUILD_RAIL: 3,
  BUILD_STATION: 4,
  BUILD_BUS_STOP: 5,
  BUILD_TRUCK_STOP: 6,
  BUILD_AIRPORT: 7,
  BUILD_DOCK: 8,
  BUILD_BRIDGE: 9,
  TERRAIN_LOWER: 10,
  TERRAIN_RAISE: 11,
  FILL_WATER: 12,
  CREATE_WATER: 13,
  PLANT_TREES: 14,
  SIGNAL: 15,
};

export const TOOL_NAMES = {
  [TOOLS.CURSOR]: 'Select',
  [TOOLS.DEMOLISH]: 'Demolish',
  [TOOLS.BUILD_ROAD]: 'Road',
  [TOOLS.BUILD_RAIL]: 'Rail',
  [TOOLS.BUILD_STATION]: 'Station',
  [TOOLS.BUILD_BUS_STOP]: 'Bus Stop',
  [TOOLS.BUILD_TRUCK_STOP]: 'Truck Stop',
  [TOOLS.BUILD_AIRPORT]: 'Airport',
  [TOOLS.BUILD_DOCK]: 'Dock',
  [TOOLS.BUILD_BRIDGE]: 'Bridge',
  [TOOLS.TERRAIN_LOWER]: 'Lower Land',
  [TOOLS.TERRAIN_RAISE]: 'Raise Land',
  [TOOLS.FILL_WATER]: 'Fill Water',
  [TOOLS.CREATE_WATER]: 'Create Water',
  [TOOLS.PLANT_TREES]: 'Plant Trees',
  [TOOLS.SIGNAL]: 'Signal',
};

export const TOOL_ICONS = {
  [TOOLS.CURSOR]: '🔍',
  [TOOLS.DEMOLISH]: '💥',
  [TOOLS.BUILD_ROAD]: '🛣️',
  [TOOLS.BUILD_RAIL]: '🛤️',
  [TOOLS.BUILD_STATION]: '🚉',
  [TOOLS.BUILD_BUS_STOP]: '🚌',
  [TOOLS.BUILD_TRUCK_STOP]: '🚛',
  [TOOLS.BUILD_AIRPORT]: '✈️',
  [TOOLS.BUILD_DOCK]: '⚓',
  [TOOLS.BUILD_BRIDGE]: '🌉',
  [TOOLS.TERRAIN_LOWER]: '⬇️',
  [TOOLS.TERRAIN_RAISE]: '⬆️',
  [TOOLS.FILL_WATER]: '🧱',
  [TOOLS.CREATE_WATER]: '💧',
  [TOOLS.PLANT_TREES]: '🌲',
  [TOOLS.SIGNAL]: '🚦',
};

// Build costs per tile
export const BUILD_COSTS = {
  [TOOLS.DEMOLISH]: 100,
  [TOOLS.BUILD_ROAD]: 50,
  [TOOLS.BUILD_RAIL]: 150,
  [TOOLS.BUILD_STATION]: 1500,
  [TOOLS.BUILD_BUS_STOP]: 500,
  [TOOLS.BUILD_TRUCK_STOP]: 500,
  [TOOLS.BUILD_AIRPORT]: 50000,
  [TOOLS.BUILD_DOCK]: 10000,
  [TOOLS.BUILD_BRIDGE]: 200,
  [TOOLS.TERRAIN_LOWER]: 200,
  [TOOLS.TERRAIN_RAISE]: 200,
  [TOOLS.FILL_WATER]: 300,
  [TOOLS.CREATE_WATER]: 300,
  [TOOLS.PLANT_TREES]: 5,
  [TOOLS.SIGNAL]: 100,
};

// Station sizes (in tiles)
export const STATION_SIZES = {
  [TOOLS.BUILD_STATION]: 8,     // train station: 8 tiles long
  [TOOLS.BUILD_BUS_STOP]: 2,     // bus stop: 2 tiles
  [TOOLS.BUILD_TRUCK_STOP]: 2,   // truck stop: 2 tiles
  [TOOLS.BUILD_AIRPORT]: 11,     // airport: 11x11
  [TOOLS.BUILD_DOCK]: 3,         // dock: 3 tiles
};

// Vehicle classes
export const VEHICLE_CLASSES = {
  TRAIN: 'train',
  ROAD: 'road',
  AIR: 'air',
  WATER: 'water',
};

export const VEHICLE_CLASS_SURFACE = {
  [VEHICLE_CLASSES.TRAIN]: TILE.RAIL,
  [VEHICLE_CLASSES.ROAD]: TILE.ROAD,
  [VEHICLE_CLASSES.AIR]: TILE.AIRPORT,
  [VEHICLE_CLASSES.WATER]: TILE.DOCK,
};

// Cargo types
export const CARGO_TYPES = [
  { id: 0, name: 'Passengers', color: '#00ff00', value: 1 },
  { id: 1, name: 'Mail', color: '#ffff00', value: 2 },
  { id: 2, name: 'Coal', color: '#333333', value: 3 },
  { id: 3, name: 'Iron Ore', color: '#8b4513', value: 3 },
  { id: 4, name: 'Stone', color: '#888888', value: 2 },
  { id: 5, name: 'Wood', color: '#228b22', value: 3 },
  { id: 6, name: 'Food', color: '#9acd32', value: 3 },
  { id: 7, name: 'Oil', color: '#1a1a1a', value: 4 },
  { id: 8, name: 'Steel', color: '#b22222', value: 5 },
  { id: 9, name: 'Paper', color: '#f5f5dc', value: 4 },
  { id: 10, name: 'Baked Goods', color: '#daa520', value: 4 },
  { id: 11, name: 'Cars', color: '#4169e1', value: 6 },
  { id: 12, name: 'Fuel', color: '#dc143c', value: 5 },
  { id: 13, name: 'Satellite', color: '#9370db', value: 10 },
];

// Industry definitions
export const INDUSTRY_TYPES = [
  { id: 0, name: 'Coal Mine', produces: 'Coal', producesCargoId: 2, minYear: 1920, color: '#333333' },
  { id: 1, name: 'Iron Ore Mine', produces: 'Iron Ore', producesCargoId: 3, minYear: 1920, color: '#8b4513' },
  { id: 2, name: 'Quarry', produces: 'Stone', producesCargoId: 4, minYear: 1920, color: '#888888' },
  { id: 3, name: 'Lumber Mill', produces: 'Wood', producesCargoId: 5, minYear: 1920, color: '#228b22' },
  { id: 4, name: 'Farm', produces: 'Food', producesCargoId: 6, minYear: 1920, color: '#9acd32' },
  { id: 5, name: 'Oil Well', produces: 'Oil', producesCargoId: 7, minYear: 1920, color: '#1a1a1a' },
  { id: 6, name: 'Steelworks', produces: 'Steel', producesCargoId: 8, consumes: 'Iron Ore', consumesCargoId: 3, minYear: 1930, color: '#b22222' },
  { id: 7, name: 'Paper Mill', produces: 'Paper', producesCargoId: 9, consumes: 'Wood', consumesCargoId: 5, minYear: 1930, color: '#f5f5dc' },
  { id: 8, name: 'Bakery', produces: 'Baked Goods', producesCargoId: 10, consumes: 'Food', consumesCargoId: 6, minYear: 1935, color: '#daa520' },
  { id: 9, name: 'Car Factory', produces: 'Cars', producesCargoId: 11, consumes: 'Steel', consumesCargoId: 8, minYear: 1950, color: '#4169e1' },
  { id: 10, name: 'Refinery', produces: 'Fuel', producesCargoId: 12, consumes: 'Oil', consumesCargoId: 7, minYear: 1940, color: '#dc143c' },
  { id: 11, name: 'Spaceport', produces: 'Satellite', producesCargoId: 13, consumes: 'Cars', consumesCargoId: 11, minYear: 1969, color: '#9370db' },
];

// Vehicle definitions
export const VEHICLE_DEFS = [
  // Trains (id 0-5)
  { id: 0, name: 'Steam Loco', cls: VEHICLE_CLASSES.TRAIN, type: 'engine', speed: 60, power: 200, cost: 8000, capacity: 0, reliability: 80, minYear: 1920, color: '#8b4513', maintenance: 200 },
  { id: 1, name: 'Diesel Loco', cls: VEHICLE_CLASSES.TRAIN, type: 'engine', speed: 100, power: 350, cost: 25000, capacity: 0, reliability: 90, minYear: 1935, color: '#228b22', maintenance: 350 },
  { id: 2, name: 'Electric Loco', cls: VEHICLE_CLASSES.TRAIN, type: 'engine', speed: 140, power: 500, cost: 60000, capacity: 0, reliability: 95, minYear: 1950, color: '#4169e1', maintenance: 500 },
  { id: 3, name: 'High Speed', cls: VEHICLE_CLASSES.TRAIN, type: 'engine', speed: 220, power: 800, cost: 150000, capacity: 0, reliability: 98, minYear: 1965, color: '#dc143c', maintenance: 800 },
  { id: 4, name: 'Passenger Car', cls: VEHICLE_CLASSES.TRAIN, type: 'wagon', speed: 0, power: 0, cost: 4000, capacity: 32, cargoTypes: [0], reliability: 85, minYear: 1920, color: '#228b22', maintenance: 100 },
  { id: 5, name: 'Cargo Wagon', cls: VEHICLE_CLASSES.TRAIN, type: 'wagon', speed: 0, power: 0, cost: 3000, capacity: 20, cargoTypes: [2,3,4,5,6,7,8,9,10,11,12,13], reliability: 85, minYear: 1920, color: '#8b4513', maintenance: 80 },
  // Road vehicles (id 6-11)
  { id: 6, name: 'Minibus', cls: VEHICLE_CLASSES.ROAD, type: 'single', speed: 50, power: 0, cost: 2000, capacity: 12, cargoTypes: [0], reliability: 75, minYear: 1920, color: '#ff6347', maintenance: 100 },
  { id: 7, name: 'Bus', cls: VEHICLE_CLASSES.ROAD, type: 'single', speed: 65, power: 0, cost: 5000, capacity: 28, cargoTypes: [0], reliability: 80, minYear: 1930, color: '#228b22', maintenance: 150 },
  { id: 8, name: 'Coach', cls: VEHICLE_CLASSES.ROAD, type: 'single', speed: 80, power: 0, cost: 12000, capacity: 60, cargoTypes: [0], reliability: 85, minYear: 1945, color: '#4169e1', maintenance: 250 },
  { id: 9, name: 'Cargo Truck', cls: VEHICLE_CLASSES.ROAD, type: 'single', speed: 55, power: 0, cost: 4000, capacity: 10, cargoTypes: [2,3,4,5,6,7,8,9,10,11,12], reliability: 75, minYear: 1920, color: '#8b4513', maintenance: 120 },
  { id: 10, name: 'Long Dist. Truck', cls: VEHICLE_CLASSES.ROAD, type: 'single', speed: 70, power: 0, cost: 8000, capacity: 16, cargoTypes: [2,3,4,5,6,7,8,9,10,11,12], reliability: 80, minYear: 1940, color: '#b8860b', maintenance: 200 },
  { id: 11, name: 'Mail Van', cls: VEHICLE_CLASSES.ROAD, type: 'single', speed: 55, power: 0, cost: 3000, capacity: 8, cargoTypes: [1], reliability: 75, minYear: 1920, color: '#ffff00', maintenance: 100 },
  // Aircraft (id 12-16)
  { id: 12, name: 'Cessna', cls: VEHICLE_CLASSES.AIR, type: 'single', speed: 200, power: 0, cost: 15000, capacity: 8, cargoTypes: [0], reliability: 85, minYear: 1935, color: '#ffffff', maintenance: 400 },
  { id: 13, name: 'DC-3', cls: VEHICLE_CLASSES.AIR, type: 'single', speed: 250, power: 0, cost: 45000, capacity: 24, cargoTypes: [0], reliability: 90, minYear: 1940, color: '#c0c0c0', maintenance: 600 },
  { id: 14, name: 'Boeing 707', cls: VEHICLE_CLASSES.AIR, type: 'single', speed: 500, power: 0, cost: 180000, capacity: 160, cargoTypes: [0], reliability: 95, minYear: 1958, color: '#4169e1', maintenance: 1200 },
  { id: 15, name: 'Cargo Plane', cls: VEHICLE_CLASSES.AIR, type: 'single', speed: 350, power: 0, cost: 120000, capacity: 60, cargoTypes: [2,3,4,5,6,8,9,10,11,12,13], reliability: 90, minYear: 1950, color: '#8b4513', maintenance: 900 },
  { id: 16, name: 'Air Mail', cls: VEHICLE_CLASSES.AIR, type: 'single', speed: 250, power: 0, cost: 40000, capacity: 20, cargoTypes: [1], reliability: 90, minYear: 1940, color: '#ffff00', maintenance: 500 },
  // Ships (id 17-19)
  { id: 17, name: 'Cargo Ship', cls: VEHICLE_CLASSES.WATER, type: 'single', speed: 30, power: 0, cost: 25000, capacity: 80, cargoTypes: [2,3,4,5,6,7,8,9,10,11,12], reliability: 85, minYear: 1920, color: '#8b4513', maintenance: 500 },
  { id: 18, name: 'Passenger Ship', cls: VEHICLE_CLASSES.WATER, type: 'single', speed: 35, power: 0, cost: 40000, capacity: 200, cargoTypes: [0], reliability: 85, minYear: 1920, color: '#228b22', maintenance: 600 },
  { id: 19, name: 'Ferry', cls: VEHICLE_CLASSES.WATER, type: 'single', speed: 40, power: 0, cost: 60000, capacity: 120, cargoTypes: [0], reliability: 90, minYear: 1935, color: '#4169e1', maintenance: 800 },
];

// Town sizes
export const TOWN_SIZES = [
  { name: 'Hamlet', minPop: 0, maxPop: 49, color: '#9acd32' },
  { name: 'Village', minPop: 50, maxPop: 99, color: '#32cd32' },
  { name: 'Town', minPop: 100, maxPop: 249, color: '#228b22' },
  { name: 'City', minPop: 250, maxPop: 499, color: '#006400' },
  { name: 'Metropolis', minPop: 500, maxPop: 9999, color: '#004d00' },
];

// Economy
export const STARTING_MONEY = 100000;
export const MAX_LOAN = 4000000;
export const LOAN_STEP = 10000;
export const INTEREST_RATE = 0.05; // 5% per year
export const FARE_PER_TILE = 1.5;

// Game time
export const START_YEAR = 1920;
export const END_YEAR = 2020;
export const TICKS_PER_DAY = 1;
export const DAYS_PER_MONTH = 30;

// Game speed
export const GAME_SPEED = {
  PAUSED: 0,
  NORMAL: 1,
  FAST: 3,
  FASTEST: 6,
};

export const GAME_SPEED_NAMES = {
  [GAME_SPEED.PAUSED]: '⏸',
  [GAME_SPEED.NORMAL]: '▶',
  [GAME_SPEED.FAST]: '⏩',
  [GAME_SPEED.FASTEST]: '⏭',
};

export const MONTH_NAMES = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

// Difficulty presets
export const DIFFICULTY = {
  easy: { money: 200000, maxLoan: 4000000, interest: 0.03, target: 2000000, costMult: 0.8 },
  normal: { money: 100000, maxLoan: 4000000, interest: 0.05, target: 4000000, costMult: 1.0 },
  hard: { money: 50000, maxLoan: 2000000, interest: 0.08, target: 8000000, costMult: 1.5 },
};

// Win/lose
export const WIN_TARGET = 4000000;
export const LOSE_MONEY = -500000;
