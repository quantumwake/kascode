// ===== MAIN APP COMPONENT =====

import React, { useReducer, useCallback, useEffect, useRef, useState } from 'react';
import {
  MAP_SIZE, TOOLS, TOOL_NAMES, TOOL_ICONS, BUILD_COSTS, GAME_SPEED, GAME_SPEED_NAMES,
  MONTH_NAMES, VEHICLE_DEFS, VEHICLE_CLASSES, TERRAIN, TILE
} from './game/constants.js';
import { createNewGame, ACTIONS, buildStation, buyVehicle, scrapVehicle, setVehicleRoute } from './game/state.js';
import { gameTick } from './game/simulation.js';
import { saveGame, loadGame, getSavedGames, deleteSave, loadGameFromFile, saveGameAsFile } from './game/saveLoad.js';
import { playClick, playBuild, playError, playCash, initAudio } from './audio/sounds.js';
import GameCanvas from './rendering/renderer.jsx';
import Toolbar from './ui/Toolbar.jsx';
import VehiclePanel from './ui/VehiclePanel.jsx';
import EconomyPanel from './ui/EconomyPanel.jsx';
import SaveLoadPanel from './ui/SaveLoadPanel.jsx';
import InfoPanel from './ui/InfoPanel.jsx';
import NewGameModal from './ui/NewGameModal.jsx';

// ---- Game Reducer ----

function gameReducer(state, action) {
  if (!state) {
    // Initial state - show title screen
    return { gameState: null, uiState: { showTitle: true } };
  }

  switch (action.type) {
    case ACTIONS.NEW_GAME: {
      const newGame = createNewGame(action.payload.seed, action.payload.difficulty);
      return { ...state, gameState: newGame, uiState: { ...state.uiState, showTitle: false } };
    }

    case ACTIONS.LOAD_GAME: {
      return { ...state, gameState: action.payload, uiState: { ...state.uiState, showTitle: false } };
    }

    case ACTIONS.TICK: {
      if (!state.gameState) return state;
      const newGS = gameTick(state.gameState);
      return { ...state, gameState: newGS };
    }

    case ACTIONS.CHANGE_TOOL: {
      if (!state.gameState) return state;
      playClick();
      return { ...state, gameState: { ...state.gameState, selectedTool: action.payload } };
    }

    case ACTIONS.CHANGE_SPEED: {
      if (!state.gameState) return state;
      playClick();
      return { ...state, gameState: { ...state.gameState, gameSpeed: action.payload, paused: action.payload === GAME_SPEED.PAUSED } };
    }

    case ACTIONS.TOGGLE_PAUSE: {
      if (!state.gameState) return state;
      playClick();
      const newSpeed = state.gameState.paused ? GAME_SPEED.NORMAL : GAME_SPEED.PAUSED;
      return { ...state, gameState: { ...state.gameState, paused: newSpeed === GAME_SPEED.PAUSED, gameSpeed: newSpeed } };
    }

    case ACTIONS.MOVE_CAMERA: {
      if (!state.gameState) return state;
      const speed = state.gameState.zoom > 4 ? 8 : 16;
      let { x, y } = action.payload;
      if (x === undefined) x = 0;
      if (y === undefined) y = 0;
      const gs = state.gameState;
      return { ...state, gameState: {
        ...gs,
        cameraX: Math.max(0, Math.min(MAP_SIZE - 1, gs.cameraX + x * speed)),
        cameraY: Math.max(0, Math.min(MAP_SIZE - 1, gs.cameraY + y * speed)),
      }};
    }

    case ACTIONS.ZOOM: {
      if (!state.gameState) return state;
      const gs = state.gameState;
      const newZoom = Math.max(1, Math.min(8, gs.zoom + action.payload));
      return { ...state, gameState: { ...gs, zoom: newZoom } };
    }

    case ACTIONS.SHOW_PANEL: {
      playClick();
      return { ...state, gameState: { ...state.gameState, showPanel: action.payload } };
    }

    case ACTIONS.HIDE_PANEL: {
      playClick();
      return { ...state, gameState: { ...state.gameState, showPanel: null } };
    }

    case ACTIONS.SELECT_VEHICLE: {
      if (!state.gameState) return state;
      playClick();
      return { ...state, gameState: { ...state.gameState, selectedVehicle: action.payload } };
    }

    case ACTIONS.CLEAR_NOTIFICATIONS: {
      if (!state.gameState) return state;
      return { ...state, gameState: { ...state.gameState, notifications: [] } };
    }

    case ACTIONS.TAKE_LOAN: {
      if (!state.gameState) return state;
      const gs = state.gameState;
      const newLoan = Math.min(gs.maxLoan, gs.loan + 10000);
      return { ...state, gameState: { ...gs, loan: newLoan, money: gs.money + 10000, notifications: [...gs.notifications, `Took loan: +$10,000`] } };
    }

    case ACTIONS.REPAY_LOAN: {
      if (!state.gameState) return state;
      const gs = state.gameState;
      const repay = Math.min(gs.loan, 10000);
      return { ...state, gameState: { ...gs, loan: gs.loan - repay, money: gs.money - repay, notifications: [...gs.notifications, `Repaid loan: -$${repay}`] } };
    }

    case 'SET_CAMERA': {
      if (!state.gameState) return state;
      const gs = state.gameState;
      return { ...state, gameState: { ...gs, cameraX: action.payload.x, cameraY: action.payload.y } };
    }

    case 'BUILD_TILE': {
      if (!state.gameState) return state;
      const gs = state.gameState;
      const { x, y, surfaceType, featureType, cost, notification } = action.payload;
      if (gs.money < cost) return state;
      const idx = y * MAP_SIZE + x;
      const newSurface = new Uint8Array(gs.surface);
      const newFeatures = new Uint8Array(gs.features);
      if (surfaceType !== undefined) newSurface[idx] = surfaceType;
      if (featureType !== undefined) newFeatures[idx] = featureType;
      return { ...state, gameState: { ...gs, surface: newSurface, features: newFeatures, money: gs.money - cost, notifications: [...gs.notifications, notification || ''] } };
    }

    case 'UPDATE_GAME_STATE': {
      if (!state.gameState) return state;
      return { ...state, gameState: { ...state.gameState, ...action.payload } };
    }

    default: return state;
  }
}

// ---- Main App ----

export default function App() {
  const [appState, dispatch] = useReducer(gameReducer, {
    gameState: null,
    uiState: { showTitle: true },
  });

  const gs = appState.gameState;
  const gameLoopRef = useRef(null);
  const fileInputRef = useRef(null);

  // ---- Game Loop ----
  useEffect(() => {
    if (!gs || gs.paused) {
      if (gameLoopRef.current) clearInterval(gameLoopRef.current);
      return;
    }

    gameLoopRef.current = setInterval(() => {
      for (let i = 0; i < gs.gameSpeed; i++) {
        dispatch({ type: ACTIONS.TICK });
      }
    }, 1000 / 10); // 10 ticks per second base

    return () => { if (gameLoopRef.current) clearInterval(gameLoopRef.current); };
  }, [gs?.paused, gs?.gameSpeed, gs]);

  // ---- Keyboard Controls ----
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (!gs) return;

      switch (e.key) {
        case 'ArrowLeft': case 'a': case 'A':
          dispatch({ type: ACTIONS.MOVE_CAMERA, payload: { x: -1 } }); break;
        case 'ArrowRight': case 'd': case 'D':
          dispatch({ type: ACTIONS.MOVE_CAMERA, payload: { x: 1 } }); break;
        case 'ArrowUp': case 'w': case 'W':
          dispatch({ type: ACTIONS.MOVE_CAMERA, payload: { y: -1 } }); break;
        case 'ArrowDown': case 's': case 'S':
          dispatch({ type: ACTIONS.MOVE_CAMERA, payload: { y: 1 } }); break;
        case ' ':
          e.preventDefault();
          dispatch({ type: ACTIONS.TOGGLE_PAUSE }); break;
        case 'Escape':
          dispatch({ type: ACTIONS.HIDE_PANEL }); break;
        case '+': case '=':
          dispatch({ type: ACTIONS.ZOOM, payload: 1 }); break;
        case '-': case '_':
          dispatch({ type: ACTIONS.ZOOM, payload: -1 }); break;
        default:
          // Number keys 1-9 for tools
          if (e.key >= '1' && e.key <= '9') {
            const toolIdx = parseInt(e.key) - 1;
            const tools = Object.values(TOOLS);
            if (toolIdx < tools.length) {
              dispatch({ type: ACTIONS.CHANGE_TOOL, payload: tools[toolIdx] });
            }
          }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [gs]);

  // ---- Tile Click Handler ----
  const handleTileClick = useCallback((tile) => {
    if (!gs) return;
    initAudio();

    if (tile.isMinimap) {
      dispatch({ type: 'SET_CAMERA', payload: { x: tile.x, y: tile.y } });
      return;
    }

    // Check if clicking on a vehicle
    const vehicle = gs.vehicles.find(v => v.x === tile.x && v.y === tile.y);
    if (vehicle) {
      dispatch({ type: ACTIONS.SELECT_VEHICLE, payload: vehicle.id });
      dispatch({ type: ACTIONS.SHOW_PANEL, payload: 'vehicle' });
      return;
    }

    const idx = tile.y * MAP_SIZE + tile.x;

    // Demolish
    if (gs.selectedTool === TOOLS.DEMOLISH) {
      if (gs.surface[idx] !== 0 || gs.features[idx] !== 0) {
        const cost = Math.floor(BUILD_COSTS[TOOLS.DEMOLISH] * gs.costMult);
        if (gs.money >= cost) {
          playBuild();
          dispatch({ type: 'BUILD_TILE', payload: { x: tile.x, y: tile.y, surfaceType: 0, featureType: 0, cost, notification: `Demolished (-$${cost})` } });
        } else { playError(); }
      }
      return;
    }

    // Station building
    if ([TOOLS.BUILD_STATION, TOOLS.BUILD_BUS_STOP, TOOLS.BUILD_TRUCK_STOP,
         TOOLS.BUILD_AIRPORT, TOOLS.BUILD_DOCK].includes(gs.selectedTool)) {
      const cost = Math.floor(BUILD_COSTS[gs.selectedTool] * gs.costMult);
      if (gs.money < cost) { playError(); return; }
      const newState = buildStation(gs, gs.selectedTool, tile.x, tile.y);
      if (newState !== gs) {
        playBuild();
        dispatch({ type: 'UPDATE_GAME_STATE', payload: newState });
      }
      return;
    }

    // Simple surface build (road, rail, signal, bridge)
    if ([TOOLS.BUILD_ROAD, TOOLS.BUILD_RAIL, TOOLS.SIGNAL, TOOLS.BUILD_BRIDGE].includes(gs.selectedTool)) {
      if (gs.surface[idx] !== 0) { playError(); return; }
      const surfaceType = gs.selectedTool === TOOLS.BUILD_ROAD ? TILE.ROAD :
                          gs.selectedTool === TOOLS.BUILD_RAIL ? TILE.RAIL :
                          gs.selectedTool === TOOLS.SIGNAL ? TILE.SIGNAL : TILE.BRIDGE;
      const cost = Math.floor(BUILD_COSTS[gs.selectedTool] * gs.costMult);
      if (gs.money < cost) { playError(); return; }
      playBuild();
      dispatch({ type: 'BUILD_TILE', payload: { x: tile.x, y: tile.y, surfaceType, featureType: 0, cost, notification: `Built ${TOOL_NAMES[gs.selectedTool]} (-$${cost})` } });
      return;
    }

    // Terrain tools
    if ([TOOLS.TERRAIN_LOWER, TOOLS.TERRAIN_RAISE, TOOLS.FILL_WATER, TOOLS.CREATE_WATER].includes(gs.selectedTool)) {
      const cost = Math.floor(BUILD_COSTS[gs.selectedTool] * gs.costMult);
      if (gs.money < cost) { playError(); return; }
      playBuild();
      dispatch({ type: 'BUILD_TILE', payload: { x: tile.x, y: tile.y, cost, notification: `${TOOL_NAMES[gs.selectedTool]} (-$${cost})` } });
      return;
    }

    if (gs.selectedTool === TOOLS.PLANT_TREES) {
      if (gs.terrain[idx] !== TERRAIN.GRASS) return;
      const cost = Math.floor(BUILD_COSTS[TOOLS.PLANT_TREES] * gs.costMult);
      if (gs.money < cost) { playError(); return; }
      if (gs.features[idx] !== 0) { playError(); return; }
      playBuild();
      dispatch({ type: 'BUILD_TILE', payload: { x: tile.x, y: tile.y, featureType: 1, cost, notification: `Planted tree (-$${cost})` } });
    }
  }, [gs, dispatch]);

  // ---- Tile Hover Handler ----
  const handleTileHover = useCallback((tile) => {
    if (!gs) return;
    dispatch({ type: 'UPDATE_GAME_STATE', payload: { hoveredTile: tile } });
  }, [gs, dispatch]);

  // ---- New Game ----
  const handleNewGame = useCallback((seed, difficulty) => {
    initAudio();
    dispatch({ type: ACTIONS.NEW_GAME, payload: { seed, difficulty } });
  }, [dispatch]);

  // ---- Load Game ----
  const handleLoadGame = useCallback((saveData) => {
    initAudio();
    const loaded = loadGame(saveData);
    dispatch({ type: ACTIONS.LOAD_GAME, payload: loaded });
  }, [dispatch]);

  // ---- Load from file ----
  const handleLoadFile = useCallback((e) => {
    const file = e.target.files[0];
    if (!file) return;
    loadGameFromFile(file).then(loaded => {
      dispatch({ type: ACTIONS.LOAD_GAME, payload: loaded });
    }).catch(err => console.error('Load error:', err));
    e.target.value = '';
  }, [dispatch]);

  // ---- Save Game ----
  const handleSaveGame = useCallback(() => {
    if (!gs) return;
    saveGame(gs, 'Save1');
    dispatch({ type: ACTIONS.CLEAR_NOTIFICATIONS });
  }, [gs, dispatch]);

  // ---- Title Screen ----
  if (!gs) {
    return <NewGameModal onNewGame={handleNewGame} onLoadGame={handleLoadGame} onLoadFile={handleLoadFile} />;
  }

  // ---- Game Screen ----
  return (
    <div className="game-container">
      {/* HUD Bar */}
      <div className="hud-bar">
        <div className="hud-left">
          <div className="hud-stat">
            <span className="label">Money</span>
            <span className={`value ${gs.money >= 0 ? 'money-positive' : 'money-negative'}`}>
              ${gs.money.toLocaleString()}
            </span>
          </div>
          <div className="hud-stat">
            <span className="label">Loan</span>
            <span className="value">${gs.loan.toLocaleString()}</span>
          </div>
          <div className="hud-stat">
            <span className="label">Profit</span>
            <span className={`value ${gs.monthlyProfit[gs.monthlyProfit.length - 1] >= 0 ? 'money-positive' : 'money-negative'}`}>
              ${gs.monthlyProfit.length > 0 ? gs.monthlyProfit[gs.monthlyProfit.length - 1].toLocaleString() : '0'}
            </span>
          </div>
        </div>

        <div className="hud-center">
          <div className="hud-stat">
            <span className="label">Date</span>
            <span className="value">
              {MONTH_NAMES[gs.date.getMonth()]} {gs.date.getFullYear()}
            </span>
          </div>
          <div className="hud-stat">
            <span className="label">Target</span>
            <span className="value">${(gs.targetWealth || 4000000).toLocaleString()}</span>
          </div>
        </div>

        <div className="hud-right">
          {/* Speed controls */}
          {Object.entries(GAME_SPEED_NAMES).map(([speed, label]) => (
            <button
              key={speed}
              className={`speed-btn ${gs.gameSpeed === parseInt(speed) ? 'active' : ''}`}
              onClick={() => dispatch({ type: ACTIONS.CHANGE_SPEED, payload: parseInt(speed) })}
            >
              {label}
            </button>
          ))}
          <button className="speed-btn" onClick={() => dispatch({ type: ACTIONS.SHOW_PANEL, payload: 'economy' })}>
            📊
          </button>
          <button className="speed-btn" onClick={handleSaveGame}>
            💾
          </button>
          <button className="speed-btn" onClick={() => dispatch({ type: ACTIONS.SHOW_PANEL, payload: 'saveload' })}>
            📁
          </button>
        </div>
      </div>

      {/* Game Area */}
      <div className="game-area">
        <GameCanvas
          state={gs}
          onTileClick={handleTileClick}
          onTileHover={handleTileHover}
        />

        {/* Panels */}
        {gs.showPanel === 'vehicle' && (
          <VehiclePanel state={gs} dispatch={dispatch} onClose={() => dispatch({ type: ACTIONS.HIDE_PANEL })} />
        )}
        {gs.showPanel === 'economy' && (
          <EconomyPanel state={gs} dispatch={dispatch} onClose={() => dispatch({ type: ACTIONS.HIDE_PANEL })} />
        )}
        {gs.showPanel === 'saveload' && (
          <SaveLoadPanel state={gs} dispatch={dispatch} onClose={() => dispatch({ type: ACTIONS.HIDE_PANEL })}
            onLoadGame={handleLoadGame} onLoadFile={handleLoadFile} onSave={handleSaveGame} />
        )}
        {gs.showPanel === 'info' && (
          <InfoPanel state={gs} onClose={() => dispatch({ type: ACTIONS.HIDE_PANEL })} />
        )}

        {/* Notifications */}
        {gs.notifications.length > 0 && (
          <div className="notification">
            {gs.notifications[gs.notifications.length - 1]}
          </div>
        )}
      </div>

      {/* Toolbar */}
      <Toolbar state={gs} dispatch={dispatch} />

      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".json"
        style={{ display: 'none' }}
        onChange={handleLoadFile}
      />
    </div>
  );
}
