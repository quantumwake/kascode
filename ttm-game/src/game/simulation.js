// ===== GAME SIMULATION =====
// Handles one game tick (one day)

import {
  MAP_SIZE, TERRAIN, TILE, CARGO_TYPES, VEHICLE_DEFS,
  VEHICLE_CLASSES, VEHICLE_CLASS_SURFACE, TOWN_SIZES,
  FARE_PER_TILE, DAYS_PER_MONTH, MONTH_NAMES
} from './constants.js';
import { findPath } from './state.js';

// ---- Main tick ----

export function gameTick(state) {
  if (state.paused) return state;

  let newState = { ...state };
  newState.dateTicks++;

  // Advance date
  const date = new Date(newState.date);
  date.setDate(date.getDate() + 1);
  newState.date = date;

  // ---- Vehicle simulation ----
  newState = simulateVehicles(newState);

  // ---- Monthly processing (every 30 days) ----
  if (newState.dateTicks % DAYS_PER_MONTH === 0) {
    newState = monthlyProcessing(newState);
  }

  // ---- Passenger generation (every few days) ----
  if (newState.dateTicks % 3 === 0) {
    newState = generatePassengers(newState);
  }

  // ---- Industry production (every 5 days) ----
  if (newState.dateTicks % 5 === 0) {
    newState = industryProduction(newState);
  }

  // ---- Win/Lose check ----
  if (newState.money >= (newState.targetWealth || 4000000)) {
    newState.notifications = [...newState.notifications, '🎉 Congratulations! You reached the target wealth!'];
  }
  if (newState.money < -500000 && newState.loan >= newState.maxLoan) {
    newState.notifications = [...newState.notifications, '💀 Bankruptcy! You have gone bankrupt!'];
    newState.paused = true;
    newState.gameSpeed = 0;
  }

  return newState;
}

// ---- Vehicle Simulation ----

function simulateVehicles(state) {
  let totalIncome = 0;
  let updatedStations = state.stations.map(s => ({ ...s, waitingCargo: { ...s.waitingCargo } }));

  const newVehicles = state.vehicles.map(vehicle => {
    if (vehicle.brokenDown) {
      vehicle.breakdownTimer--;
      if (vehicle.breakdownTimer <= 0) {
        return { ...vehicle, brokenDown: false, state: 'idle' };
      }
      return vehicle;
    }

    // Check for breakdown
    const def = VEHICLE_DEFS[vehicle.defId];
    if (Math.random() * 100 < (100 - def.reliability) / 365) {
      return { ...vehicle, brokenDown: true, breakdownTimer: 30 + Math.floor(Math.random() * 60) };
    }

    // If idle, find cargo
    if (vehicle.state === 'idle') {
      const result = tryLoadCargo(updatedStations, vehicle);
      if (result.stationsChanged) updatedStations = result.stations;
      return result.vehicle;
    }

    // If loading
    if (vehicle.state === 'loading') {
      const station = updatedStations.find(s => s.id === vehicle.stationId);
      if (!station) return { ...vehicle, state: 'idle' };
      const result = loadFromStation(station, vehicle);
      if (result.stationsChanged) updatedStations = result.stations;
      const hasC = result.cargo.length > 0;
      return { ...result.vehicle, state: hasC ? 'moving' : 'idle' };
    }

    // If unloading
    if (vehicle.state === 'unloading') {
      const result = unloadAtStation(updatedStations, vehicle);
      totalIncome += result.income;
      const nextStationId = getNextStationInRoute(result.vehicle);
      if (nextStationId === null) {
        return { ...result.vehicle, state: 'idle', stationId: vehicle.route.length > 0 ? vehicle.route[0] : vehicle.stationId };
      }
      return { ...result.vehicle, state: 'moving', stationId: nextStationId };
    }

    // Moving - advance towards target
    return moveVehicle(state, vehicle);
  });

  return { ...state, vehicles: newVehicles, stations: updatedStations, money: state.money + totalIncome };
}

function tryLoadCargo(stations, vehicle) {
  const def = VEHICLE_DEFS[vehicle.defId];
  const station = stations.find(s => s.id === vehicle.stationId);
  if (!station) return { vehicle, stationsChanged: false };

  // Check if there's cargo we can carry at this station
  if (def.cargoTypes.includes(0) && station.waitingPassengers > 0) {
    return { vehicle: { ...vehicle, state: 'loading' }, stationsChanged: false };
  }
  if (def.cargoTypes.includes(1) && station.waitingMail > 0) {
    return { vehicle: { ...vehicle, state: 'loading' }, stationsChanged: false };
  }
  for (const cargoId of def.cargoTypes) {
    if (cargoId <= 1) continue;
    if (station.waitingCargo && station.waitingCargo[cargoId] && station.waitingCargo[cargoId] > 0) {
      return { vehicle: { ...vehicle, state: 'loading' }, stationsChanged: false };
    }
  }

  // If vehicle has a route, move to next station
  if (vehicle.route.length > 0) {
    const nextIdx = vehicle.routeIndex + 1;
    if (nextIdx < vehicle.route.length) {
      return { vehicle: { ...vehicle, routeIndex: nextIdx, state: 'moving' }, stationsChanged: false };
    }
  }

  return { vehicle, stationsChanged: false };
}

function getNextStationInRoute(vehicle) {
  if (vehicle.route.length === 0) return null;
  const nextIdx = vehicle.routeIndex + 1;
  if (nextIdx >= vehicle.route.length) return null;
  return vehicle.route[nextIdx];
}

function loadFromStation(station, vehicle) {
  const def = VEHICLE_DEFS[vehicle.defId];
  let remainingCapacity = def.capacity;
  let newCargo = vehicle.cargo.map(c => ({ ...c }));
  let stationsChanged = false;

  // Load passengers
  if (def.cargoTypes.includes(0) && station.waitingPassengers > 0) {
    const count = Math.min(station.waitingPassengers, remainingCapacity);
    const existing = newCargo.find(c => c.type === 0);
    if (existing) existing.amount += count;
    else newCargo.push({ type: 0, amount: count, source: station.id });
    station.waitingPassengers -= count;
    remainingCapacity -= count;
    stationsChanged = true;
  }

  // Load mail
  if (def.cargoTypes.includes(1) && station.waitingMail > 0) {
    const count = Math.min(station.waitingMail, remainingCapacity);
    const existing = newCargo.find(c => c.type === 1);
    if (existing) existing.amount += count;
    else newCargo.push({ type: 1, amount: count, source: station.id });
    station.waitingMail -= count;
    remainingCapacity -= count;
    stationsChanged = true;
  }

  // Load goods
  for (const cargoId of def.cargoTypes) {
    if (cargoId <= 1 || remainingCapacity <= 0) continue;
    if (station.waitingCargo && station.waitingCargo[cargoId] && station.waitingCargo[cargoId] > 0) {
      const count = Math.min(station.waitingCargo[cargoId], remainingCapacity);
      const existing = newCargo.find(c => c.type === cargoId);
      if (existing) existing.amount += count;
      else newCargo.push({ type: cargoId, amount: count, source: station.id });
      station.waitingCargo[cargoId] -= count;
      remainingCapacity -= count;
      stationsChanged = true;
    }
  }

  // Clean up empty cargo entries
  newCargo = newCargo.filter(c => c.amount > 0);

  return { vehicle: { ...vehicle, cargo: newCargo }, stationsChanged };
}

function unloadAtStation(stations, vehicle) {
  const def = VEHICLE_DEFS[vehicle.defId];
  const destStation = stations.find(s => s.id === vehicle.stationId);
  if (!destStation) return { vehicle, income: 0 };

  let income = 0;

  for (const cargo of vehicle.cargo) {
    const cargoDef = CARGO_TYPES[cargo.type];
    if (!cargoDef) continue;

    // Calculate distance for fare
    const sourceStation = stations.find(s => s.id === cargo.source);
    let distance = 1;
    if (sourceStation && destStation) {
      distance = Math.max(1, Math.hypot(sourceStation.x - destStation.x, sourceStation.y - destStation.y));
    }

    const fare = Math.floor(cargoDef.value * distance * FARE_PER_TILE);
    income += fare * cargo.amount;

    // Boost service rating for nearby towns
    // (simplified - in full game, track per-town)
  }

  return { vehicle: { ...vehicle, cargo: [] }, income };
}

function moveVehicle(state, vehicle) {
  const def = VEHICLE_DEFS[vehicle.defId];
  const targetStation = state.stations.find(s => s.id === vehicle.stationId) ||
                        state.docks.find(d => d.id === vehicle.stationId) ||
                        state.airports.find(a => a.id === vehicle.stationId);
  if (!targetStation) return { ...vehicle, state: 'idle' };

  // Already at target
  if (vehicle.x === targetStation.x && vehicle.y === targetStation.y) {
    if (vehicle.cargo.length > 0) {
      return { ...vehicle, state: 'unloading' };
    }
    if (vehicle.route.length > 0) {
      const nextIdx = vehicle.routeIndex + 1;
      if (nextIdx < vehicle.route.length) {
        return { ...vehicle, routeIndex: nextIdx, state: 'loading' };
      }
    }
    return { ...vehicle, state: 'idle' };
  }

  // Find path to target
  const requiredSurface = VEHICLE_CLASS_SURFACE[def.cls];
  const path = findPath(state.surface, state.terrain, vehicle.x, vehicle.y,
    targetStation.x, targetStation.y, requiredSurface, 2000);

  if (!path || path.length === 0) {
    return { ...vehicle, state: 'idle' };
  }

  // Move one step along path
  const speedFactor = def.speed / 100;
  const step = Math.max(1, Math.floor(speedFactor));
  const nextPos = path[Math.min(step - 1, path.length - 1)];
  return { ...vehicle, x: nextPos.x, y: nextPos.y };
}

// ---- Monthly Processing ----

function monthlyProcessing(state) {
  let newState = { ...state };
  let income = 0;
  let expenses = 0;

  // Vehicle maintenance
  for (const v of newState.vehicles) {
    const def = VEHICLE_DEFS[v.defId];
    if (def) expenses += def.maintenance;
  }

  // Loan interest
  if (newState.loan > 0) {
    const interest = Math.floor(newState.loan * newState.interestRate / 12);
    expenses += interest;
  }

  // Town growth
  const newTowns = newState.towns.map(town => {
    let newTown = { ...town };
    if (newTown.serviceRating > 40) {
      newTown.population += Math.floor(newTown.serviceRating / 15);
    } else if (newTown.serviceRating < 20) {
      newTown.population = Math.max(10, newTown.population - 3);
    }
    newTown.population = Math.min(2000, newTown.population);
    newTown.serviceRating = Math.max(0, newTown.serviceRating - 3);
    return newTown;
  });
  newState.towns = newTowns;

  // Calculate profit
  const profit = income - expenses;
  newState.money += profit;
  newState.monthlyIncome = income;
  newState.monthlyExpenses = expenses;
  newState.monthlyProfit = [...newState.monthlyProfit.slice(-23), profit];

  return newState;
}

// ---- Passenger Generation ----

function generatePassengers(state) {
  const newTowns = state.towns.map(town => {
    const newTown = { ...town };
    const numPassengers = Math.max(1, Math.floor(town.population / 40));

    for (let i = 0; i < numPassengers; i++) {
      if (newTown.passengersWaiting >= 30) break;
      newTown.passengersWaiting++;
    }

    if (Math.random() < 0.2) {
      newTown.mailWaiting = Math.min(15, newTown.mailWaiting + 1);
    }

    return newTown;
  });

  // Distribute waiting passengers to nearest stations
  const newStations = state.stations.map(station => {
    let newStation = { ...station, waitingCargo: { ...station.waitingCargo } };
    for (const town of newTowns) {
      if (Math.hypot(town.x - station.x, town.y - station.y) < 30) {
        newStation.waitingPassengers += Math.floor(town.passengersWaiting / Math.max(1, state.stations.length));
        newStation.waitingMail += Math.floor(town.mailWaiting / Math.max(1, state.stations.length));
      }
    }
    return newStation;
  });

  // Reset town waiting counts
  const resetTowns = newTowns.map(t => ({ ...t, passengersWaiting: 0, mailWaiting: 0 }));

  return { ...state, towns: resetTowns, stations: newStations };
}

// ---- Industry Production ----

function industryProduction(state) {
  const newIndustries = state.industries.map(industry => {
    const newInd = { ...industry };

    if (!newInd.active) return newInd;

    // Check if it needs input cargo
    if (newInd.consumesCargoId !== null) {
      // Simplified: industry needs to be connected to produce
      // In full game, check if it received the needed input
      if (!newInd.connected) return newInd;
    }

    // Produce output
    if (newInd.storage < newInd.maxStorage) {
      newInd.storage = Math.min(newInd.maxStorage, newInd.storage + newInd.productionRate);
    }

    // Auto-connect if near a station with road
    for (const station of state.stations) {
      if (Math.hypot(station.x - newInd.x, station.y - newInd.y) < 20) {
        newInd.connected = true;
      }
    }

    // Add cargo to nearest station
    if (newInd.storage >= 5) {
      const transfer = Math.min(newInd.storage, 5);
      const newStations = state.stations.map(station => {
        if (Math.hypot(station.x - newInd.x, station.y - newInd.y) < 25) {
          const newStation = { ...station, waitingCargo: { ...station.waitingCargo } };
          if (!newStation.waitingCargo[newInd.producesCargoId]) {
            newStation.waitingCargo[newInd.producesCargoId] = 0;
          }
          newStation.waitingCargo[newInd.producesCargoId] += transfer;
          return newStation;
        }
        return station;
      });

      // Update stations in state
      if (newStations !== state.stations) {
        // This is handled at the outer level
      }

      return { ...newInd, storage: newInd.storage - transfer };
    }

    return newInd;
  });

  // Re-collect station updates
  let updatedStations = state.stations;
  for (const ind of newIndustries) {
    if (ind.storage < (state.industries.find(i => i.id === ind.id)?.storage ?? 999)) {
      // This industry produced and transferred cargo
      updatedStations = updatedStations.map(station => {
        if (Math.hypot(station.x - ind.x, station.y - ind.y) < 25) {
          const newStation = { ...station, waitingCargo: { ...station.waitingCargo } };
          if (!newStation.waitingCargo[ind.producesCargoId]) {
            newStation.waitingCargo[ind.producesCargoId] = 0;
          }
          // Add some cargo
          const origInd = state.industries.find(i => i.id === ind.id);
          const produced = (origInd?.storage ?? 0) - ind.storage;
          if (produced > 0) {
            newStation.waitingCargo[ind.producesCargoId] += Math.min(produced, 3);
          }
          return newStation;
        }
        return station;
      });
    }
  }

  return { ...state, industries: newIndustries, stations: updatedStations };
}
