// Game Constants
export const MAP_SIZE = 512; // map is 512x512 tiles
export const TILE_SIZE = 16; // base tile size in pixels

export const TERRAIN = {
  GRASS: 0,
  WATER: 1,
  HILLS: 2,
  MOUNTAIN: 3,
  DESERT: 4,
  SNOW: 5,
};

export const TERRAIN_COLORS = {
  [TERRAIN.GRASS]: '#4a8c3f',
  [TERRAIN.WATER]: '#2980b9',
  [TERRAIN.HILLS]: '#6b8e4e',
  [TERRAIN.MOUNTAIN]: '#8b7d5b',
  [TERRAIN.DESERT]: '#d4a76a',
  [TERRAIN.SNOW]: '#e8e8f0',
};

export const TILE = {
  GRASS: 0,
  WATER: 1,
  ROAD: 2,
  RAIL: 3,
  STATION: 4,
  BUS_STOP: 5,
  TRUCK_STOP: 6,
  AIRPORT: 7,
  DOCK: 8,
  TOWN: 9,
  INDUSTRY: 10,
  BRIDGE: 11,
  TUNNEL: 12,
  SIGNAL: 13,
  TREE: 14,
  HOUSE: 15,
};

export const BUILD_COSTS = {
  [TILE.ROAD]: 200,
  [TILE.RAIL]: 400,
  [TILE.STATION]: 5000,
  [TILE.BUS_STOP]: 1500,
  [TILE.TRUCK_STOP]: 1500,
  [TILE.AIRPORT]: 80000,
  [TILE.DOCK]: 15000,
  [TILE.BRIDGE]: 2500,
  [TILE.TUNNEL]: 3000,
  [TILE.SIGNAL]: 200,
};

export const CARGO_TYPES = {
  PASSENGERS: { id: 0, name: 'Passengers', color: '#2ecc71', value: 1 },
  MAIL: { id: 1, name: 'Mail', color: '#3498db', value: 2 },
  COAL: { id: 2, name: 'Coal', color: '#2c3e50', value: 3 },
  IRON_ORE: { id: 3, name: 'Iron Ore', color: '#e67e22', value: 3 },
  WOOD: { id: 4, name: 'Wood', color: '#8B4513', value: 3 },
  FOOD: { id: 5, name: 'Food', color: '#f1c40f', value: 2 },
  STEEL: { id: 6, name: 'Steel', color: '#95a5a6', value: 4 },
  OIL: { id: 7, name: 'Oil', color: '#1a1a1a', value: 4 },
  STONE: { id: 8, name: 'Stone', color: '#7f8c8d', value: 2 },
  PAPER: { id: 9, name: 'Paper', color: '#ecf0f1', value: 3 },
  CARS: { id: 10, name: 'Cars', color: '#e74c3c', value: 5 },
  FUEL: { id: 11, name: 'Fuel', color: '#e74c3c', value: 4 },
};

export const INDUSTRY_TYPES = [
  { id: 0, name: 'Coal Mine', produces: 'COAL', consumes: null, color: '#2c3e50', minYear: 1920 },
  { id: 1, name: 'Iron Ore Mine', produces: 'IRON_ORE', consumes: null, color: '#e67e22', minYear: 1920 },
  { id: 2, name: 'Quarry', produces: 'STONE', consumes: null, color: '#7f8c8d', minYear: 1920 },
  { id: 3, name: 'Lumber Mill', produces: 'WOOD', consumes: null, color: '#8B4513', minYear: 1920 },
  { id: 4, name: 'Farm', produces: 'FOOD', consumes: null, color: '#f1c40f', minYear: 1920 },
  { id: 5, name: 'Oil Well', produces: 'OIL', consumes: null, color: '#1a1a1a', minYear: 1925 },
  { id: 6, name: 'Steelworks', produces: 'STEEL', consumes: 'IRON_ORE', color: '#95a5a6', minYear: 1930 },
  { id: 7, name: 'Paper Mill', produces: 'PAPER', consumes: 'WOOD', color: '#ecf0f1', minYear: 1935 },
  { id: 8, name: 'Bakery', produces: 'FOOD', consumes: 'FOOD', color: '#f39c12', minYear: 1920 },
  { id: 9, name: 'Car Factory', produces: 'CARS', consumes: 'STEEL', color: '#e74c3c', minYear: 1950 },
  { id: 10, name: 'Refinery', produces: 'FUEL', consumes: 'OIL', color: '#c0392b', minYear: 1940 },
  { id: 11, name: 'Spaceport', produces: null, consumes: 'CARS', color: '#9b59b6', minYear: 1980 },
];

export const VEHICLE_CLASSES = {
  TRAIN: 'train',
  ROAD: 'road',
  AIR: 'air',
  WATER: 'water',
};

export const VEHICLE_DEFS = [
  // Trains
  { id: 0, name: 'Steam Locomotive', cls: 'train', speed: 60, capacity: 8, cost: 8000, maintenance: 50, year: 1920, color: '#8B0000' },
  { id: 1, name: 'Diesel Locomotive', cls: 'train', speed: 90, capacity: 12, cost: 15000, maintenance: 80, year: 1935, color: '#228B22' },
  { id: 2, name: 'Electric Locomotive', cls: 'train', speed: 120, capacity: 16, cost: 30000, maintenance: 120, year: 1950, color: '#4169E1' },
  { id: 3, name: 'High Speed Train', cls: 'train', speed: 200, capacity: 32, cost: 80000, maintenance: 250, year: 1970, color: '#FF4500' },
  { id: 4, name: 'Freight Wagon', cls: 'train', speed: 50, capacity: 20, cost: 5000, maintenance: 40, year: 1920, color: '#556B2F' },

  // Road vehicles
  { id: 5, name: 'Minibus', cls: 'road', speed: 50, capacity: 10, cost: 3000, maintenance: 30, year: 1920, color: '#FFD700' },
  { id: 6, name: 'Bus', cls: 'road', speed: 60, capacity: 20, cost: 5000, maintenance: 50, year: 1925, color: '#FF6347' },
  { id: 7, name: 'Coach', cls: 'road', speed: 70, capacity: 40, cost: 10000, maintenance: 80, year: 1935, color: '#4682B4' },
  { id: 8, name: 'Cargo Truck', cls: 'road', speed: 55, capacity: 12, cost: 4000, maintenance: 45, year: 1920, color: '#2E8B57' },
  { id: 9, name: 'Large Truck', cls: 'road', speed: 50, capacity: 25, cost: 8000, maintenance: 70, year: 1940, color: '#B8860B' },

  // Aircraft
  { id: 10, name: 'Propeller Plane', cls: 'air', speed: 250, capacity: 16, cost: 40000, maintenance: 300, year: 1935, color: '#F0F0F0' },
  { id: 11, name: 'Jet Aircraft', cls: 'air', speed: 500, capacity: 40, cost: 120000, maintenance: 800, year: 1960, color: '#1E90FF' },
  { id: 12, name: 'Cargo Plane', cls: 'air', speed: 300, capacity: 50, cost: 80000, maintenance: 500, year: 1950, color: '#696969' },

  // Ships
  { id: 13, name: 'Cargo Ship', cls: 'water', speed: 35, capacity: 60, cost: 35000, maintenance: 250, year: 1920, color: '#483D8B' },
  { id: 14, name: 'Passenger Ship', cls: 'water', speed: 40, capacity: 80, cost: 50000, maintenance: 350, year: 1925, color: '#DC143C' },
  { id: 15, name: 'Ferry', cls: 'water', speed: 45, capacity: 40, cost: 25000, maintenance: 200, year: 1930, color: '#20B2AA' },
];

export const TOWN_SIZES = {
  HAMLET: { name: 'Hamlet', popMin: 0, popMax: 99, color: '#90EE90' },
  VILLAGE: { name: 'Village', popMin: 100, popMax: 249, color: '#32CD32' },
  TOWN: { name: 'Town', popMin: 250, popMax: 499, color: '#228B22' },
  CITY: { name: 'City', popMin: 500, popMax: 999, color: '#006400' },
  METROPOLIS: { name: 'Metropolis', popMin: 1000, popMax: 9999, color: '#004d00' },
};

export const TOOLS = {
  CURSOR: 0,
  ROAD: 1,
  DEMOLISH_ROAD: 2,
  RAIL: 3,
  DEMOLISH_RAIL: 4,
  STATION: 5,
  BUS_STOP: 6,
  TRUCK_STOP: 7,
  AIRPORT: 8,
  DOCK: 9,
  BRIDGE: 10,
  TREE: 11,
  LEVEL_LAND: 12,
  FILL_LAND: 13,
  LOWER_LAND: 14,
  BUY_VEHICLE: 15,
  PAINT: 16,
};

export const GAME_SPEED = {
  PAUSED: 0,
  NORMAL: 1,
  FAST: 2,
  FASTEST: 4,
};

export const STARTING_MONEY = 100000;
export const MAX_LOAN = 4000000;
export const LOAN_STEP = 10000;
export const INTEREST_RATE = 0.05;

export const START_YEAR = 1920;
export const END_YEAR = 2020;
