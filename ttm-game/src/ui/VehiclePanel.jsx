// ===== VEHICLE PANEL =====

import React, { useState } from 'react';
import { VEHICLE_DEFS, VEHICLE_CLASSES, TOOLS } from '../game/constants.js';
import { ACTIONS, buyVehicle, scrapVehicle, setVehicleRoute } from '../game/state.js';

const CLASS_ICONS = {
  [VEHICLE_CLASSES.TRAIN]: '🚂',
  [VEHICLE_CLASSES.ROAD]: '🚌',
  [VEHICLE_CLASSES.AIR]: '✈️',
  [VEHICLE_CLASSES.WATER]: '🚢',
};

export default function VehiclePanel({ state, dispatch, onClose }) {
  const [tab, setTab] = useState('buy'); // buy, manage, routes

  const currentYear = state.date.getFullYear();
  const vehiclesByClass = {};
  VEHICLE_DEFS.forEach(v => {
    if (!vehiclesByClass[v.cls]) vehiclesByClass[v.cls] = [];
    if (v.minYear <= currentYear) vehiclesByClass[v.cls].push(v);
  });

  const handleBuy = (defId) => {
    // Need a station to buy into
    const stations = [...state.stations, ...state.docks, ...state.airports];
    if (stations.length === 0) {
      dispatch({ type: ACTIONS.CLEAR_NOTIFICATIONS });
      // Show notification about needing a station
      return;
    }
    // Buy at first compatible station
    const def = VEHICLE_DEFS[defId];
    const surfaceType = def.cls === VEHICLE_CLASSES.TRAIN ? 3 : // station
                        def.cls === VEHICLE_CLASSES.ROAD ? 4 : // bus stop
                        def.cls === VEHICLE_CLASSES.AIR ? 6 : // airport
                        def.cls === VEHICLE_CLASSES.WATER ? 7 : 0; // dock

    const station = stations.find(s => {
      if (def.cls === VEHICLE_CLASSES.TRAIN) return s.type === 3;
      if (def.cls === VEHICLE_CLASSES.ROAD) return s.type === 4 || s.type === 5;
      if (def.cls === VEHICLE_CLASSES.AIR) return s.type === 6;
      if (def.cls === VEHICLE_CLASSES.WATER) return s.type === 7;
      return true;
    });

    if (!station) {
      dispatch({ type: ACTIONS.CLEAR_NOTIFICATIONS });
      return;
    }

    const newState = buyVehicle(state, defId, station.id);
    if (newState !== state) {
      dispatch({ type: ACTIONS.LOAD_GAME, payload: newState });
    }
  };

  const handleScrap = (vehicleId) => {
    const newState = scrapVehicle(state, vehicleId);
    if (newState !== state) {
      dispatch({ type: ACTIONS.LOAD_GAME, payload: newState });
    }
  };

  return (
    <div className="panel" style={{ minWidth: '500px' }}>
      <button className="panel-close" onClick={onClose}>✕</button>
      <h2>🚂 Vehicles</h2>

      <div style={{ display: 'flex', gap: '8px', marginBottom: '16px' }}>
        {['buy', 'manage'].map(t => (
          <button key={t} className={`btn ${tab === t ? 'active' : ''}`} onClick={() => setTab(t)}>
            {t === 'buy' ? 'Buy New' : 'Manage'}
          </button>
        ))}
      </div>

      {tab === 'buy' && (
        <div>
          {Object.entries(vehiclesByClass).map(([cls, vehicles]) => (
            <div key={cls} style={{ marginBottom: '12px' }}>
              <h3 style={{ color: '#4a7aaa', fontSize: '14px', marginBottom: '6px' }}>
                {CLASS_ICONS[cls]} {cls.toUpperCase()}
              </h3>
              <div className="grid-2">
                {vehicles.map(def => {
                  const cost = Math.floor(def.cost * state.costMult);
                  const canAfford = state.money >= cost;
                  return (
                    <div key={def.id} className="vehicle-item" onClick={() => canAfford && handleBuy(def.id)}>
                      <div className="vehicle-color" style={{ background: def.color }} />
                      <div className="vehicle-info">
                        <div className="vehicle-name">{def.name}</div>
                        <div className="vehicle-detail">
                          Speed: {def.speed} | Cap: {def.capacity} | Maint: ${def.maintenance}/mo
                        </div>
                      </div>
                      <div style={{ textAlign: 'right' }}>
                        <div style={{ color: canAfford ? '#2ecc71' : '#e74c3c', fontWeight: 'bold' }}>
                          ${cost.toLocaleString()}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
          {state.stations.length === 0 && state.docks.length === 0 && state.airports.length === 0 && (
            <div style={{ padding: '12px', background: 'rgba(231,76,60,0.2)', borderRadius: '4px', color: '#e74c3c' }}>
              ⚠️ Build a station first! You need a station to buy vehicles.
            </div>
          )}
        </div>
      )}

      {tab === 'manage' && (
        <div>
          {state.vehicles.length === 0 ? (
            <div style={{ color: '#888', textAlign: 'center', padding: '20px' }}>
              No vehicles yet. Buy one from the "Buy New" tab!
            </div>
          ) : (
            state.vehicles.map(v => {
              const def = VEHICLE_DEFS[v.defId];
              if (!def) return null;
              const cargoTotal = v.cargo.reduce((s, c) => s + c.amount, 0);
              return (
                <div
                  key={v.id}
                  className={`vehicle-item ${state.selectedVehicle === v.id ? 'selected' : ''}`}
                  onClick={() => dispatch({ type: ACTIONS.SELECT_VEHICLE, payload: v.id })}
                >
                  <div className="vehicle-color" style={{ background: def.color }} />
                  <div className="vehicle-info">
                    <div className="vehicle-name">{def.name} #{v.id + 1}</div>
                    <div className="vehicle-detail">
                      {v.brokenDown ? '⚠️ Broken Down' : v.state === 'moving' ? '🚀 Moving' :
                       v.state === 'loading' ? '📦 Loading' : v.state === 'unloading' ? '📤 Unloading' : '⏸ Idle'}
                      {cargoTotal > 0 && ` | ${cargoTotal} cargo`}
                    </div>
                  </div>
                  <button
                    className="btn btn-danger"
                    style={{ padding: '4px 8px', fontSize: '11px' }}
                    onClick={(e) => { e.stopPropagation(); handleScrap(v.id); }}
                  >
                    Scrap
                  </button>
                </div>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
