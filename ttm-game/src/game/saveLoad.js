import { ACTIONS, createNewGame } from './state.js';

// Convert state to save data (only serializable parts)
export function saveGame(state, name = 'AutoSave') {
  const saveData = {
    version: 1,
    name,
    date: state.date.toISOString(),
    dateTicks: state.dateTicks,
    money: state.money,
    loan: state.loan,
    monthlyIncome: state.monthlyIncome,
    monthlyExpenses: state.monthlyExpenses,
    monthlyProfit: state.monthlyProfit,
    gameSpeed: state.gameSpeed,
    paused: state.paused,
    terrain: Array.from(state.terrain),
    features: Array.from(state.features),
    surface: Array.from(state.surface),
    stationMap: Array.from(state.stationMap),
    towns: state.towns,
    industries: state.industries,
    docks: state.docks,
    airports: state.airports,
    vehicles: state.vehicles,
    nextVehicleId: state.nextVehicleId,
    reputation: state.reputation,
    totalPassengers: state.totalPassengers,
    totalCargo: state.totalCargo,
  };

  // Save to localStorage
  const saves = getSavedGames();
  const existing = saves.findIndex(s => s.name === name);
  if (existing >= 0) {
    saves[existing] = saveData;
  } else {
    saves.push(saveData);
  }
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
  // Reconstruct state from save data
  const newState = createNewGame(0); // get structure

  return {
    ...newState,
    date: new Date(saveData.date),
    dateTicks: saveData.dateTicks,
    money: saveData.money,
    loan: saveData.loan,
    monthlyIncome: saveData.monthlyIncome,
    monthlyExpenses: saveData.monthlyExpenses,
    monthlyProfit: saveData.monthlyProfit || [],
    gameSpeed: saveData.gameSpeed,
    paused: saveData.paused,
    terrain: new Uint8Array(saveData.terrain),
    features: new Uint8Array(saveData.features),
    surface: new Uint8Array(saveData.surface),
    stationMap: new Uint8Array(saveData.stationMap),
    towns: saveData.towns || newState.towns,
    industries: saveData.industries || newState.industries,
    docks: saveData.docks || newState.docks,
    airports: saveData.airports || newState.airports,
    vehicles: saveData.vehicles || [],
    nextVehicleId: saveData.nextVehicleId || 0,
    reputation: saveData.reputation || 50,
    totalPassengers: saveData.totalPassengers || 0,
    totalCargo: saveData.totalCargo || 0,
    showPanel: null,
    notifications: [],
  };
}

export function loadGameFromFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const saveData = JSON.parse(e.target.result);
        resolve(loadGame(saveData));
      } catch (err) {
        reject(err);
      }
    };
    reader.onerror = reject;
    reader.readAsText(file);
  });
}

export function getSavedGames() {
  try {
    const data = localStorage.getItem('ttm_saves');
    return data ? JSON.parse(data) : [];
  } catch {
    return [];
  }
}

export function deleteSave(name) {
  let saves = getSavedGames();
  saves = saves.filter(s => s.name !== name);
  localStorage.setItem('ttm_saves', JSON.stringify(saves));
}

export function autoSave(state) {
  saveGame(state, 'AutoSave');
}
