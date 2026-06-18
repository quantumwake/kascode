// ===== SAVE / LOAD SYSTEM =====

import { createNewGame, ACTIONS } from './state.js';

export function saveGame(state, name = 'AutoSave') {
  const saveData = {
    version: 1,
    name,
    date: state.date.toISOString(),
    dateTicks: state.dateTicks,
    money: state.money,
    loan: state.loan,
    maxLoan: state.maxLoan,
    interestRate: state.interestRate,
    targetWealth: state.targetWealth,
    costMult: state.costMult,
    monthlyIncome: state.monthlyIncome,
    monthlyExpenses: state.monthlyExpenses,
    monthlyProfit: state.monthlyProfit,
    gameSpeed: state.gameSpeed,
    paused: state.paused,
    difficulty: state.difficulty,
    selectedTool: state.selectedTool,
    zoom: state.zoom,
    cameraX: state.cameraX,
    cameraY: state.cameraY,
    terrain: Array.from(state.terrain),
    features: Array.from(state.features),
    elevation: Array.from(state.elevation),
    surface: Array.from(state.surface),
    stationMap: Array.from(state.stationMap),
    towns: state.towns,
    industries: state.industries,
    docks: state.docks,
    airports: state.airports,
    stations: state.stations,
    nextStationId: state.nextStationId,
    vehicles: state.vehicles,
    nextVehicleId: state.nextVehicleId,
    reputation: state.reputation,
    totalPassengers: state.totalPassengers,
    totalCargo: state.totalCargo,
  };

  const saves = getSavedGames();
  const existing = saves.findIndex(s => s.name === name);
  if (existing >= 0) saves[existing] = saveData;
  else saves.push(saveData);
  // Keep max 10 saves
  if (saves.length > 10) saves.splice(0, saves.length - 10);
  localStorage.setItem('ttm_saves', JSON.stringify(saves));

  return saveData;
}

export function saveGameAsFile(state, name = 'MySave') {
  const saveData = saveGame(state, name);
  const blob = new Blob([JSON.stringify(saveData, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `ttm_save_${name.replace(/\s+/g, '_')}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

export function loadGame(saveData) {
  const base = createNewGame(0); // get structure

  return {
    ...base,
    date: new Date(saveData.date),
    dateTicks: saveData.dateTicks,
    money: saveData.money,
    loan: saveData.loan,
    maxLoan: saveData.maxLoan,
    interestRate: saveData.interestRate,
    targetWealth: saveData.targetWealth,
    costMult: saveData.costMult,
    monthlyIncome: saveData.monthlyIncome,
    monthlyExpenses: saveData.monthlyExpenses,
    monthlyProfit: saveData.monthlyProfit || [],
    gameSpeed: saveData.gameSpeed,
    paused: saveData.paused,
    difficulty: saveData.difficulty || 'normal',
    selectedTool: saveData.selectedTool,
    zoom: saveData.zoom,
    cameraX: saveData.cameraX,
    cameraY: saveData.cameraY,
    terrain: new Uint8Array(saveData.terrain),
    features: new Uint8Array(saveData.features),
    surface: new Uint8Array(saveData.surface),
    stationMap: new Uint8Array(saveData.stationMap),
    towns: saveData.towns || base.towns,
    industries: saveData.industries || base.industries,
    docks: saveData.docks || base.docks,
    airports: saveData.airports || base.airports,
    stations: saveData.stations || base.stations,
    nextStationId: saveData.nextStationId || 0,
    vehicles: saveData.vehicles || [],
    nextVehicleId: saveData.nextVehicleId || 0,
    reputation: saveData.reputation || 50,
    totalPassengers: saveData.totalPassengers || 0,
    totalCargo: saveData.totalCargo || 0,
    showPanel: null,
    notifications: [],
    buildMode: null,
    selectedVehicle: null,
    hoveredTile: null,
  };
}

export function loadGameFromFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const saveData = JSON.parse(e.target.result);
        resolve(loadGame(saveData));
      } catch (err) { reject(err); }
    };
    reader.onerror = reject;
    reader.readAsText(file);
  });
}

export function getSavedGames() {
  try {
    const data = localStorage.getItem('ttm_saves');
    return data ? JSON.parse(data) : [];
  } catch { return []; }
}

export function deleteSave(name) {
  let saves = getSavedGames();
  saves = saves.filter(s => s.name !== name);
  localStorage.setItem('ttm_saves', JSON.stringify(saves));
}

export function autoSave(state) {
  saveGame(state, 'AutoSave');
}
