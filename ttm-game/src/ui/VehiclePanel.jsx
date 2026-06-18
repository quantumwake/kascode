// ===== VEHICLE PANEL =====

import React, { useState } from 'react';
import { VEHICLE_DEFS, VEHICLE_CLASSES, TOOLS } from '../game/constants.js';
import { ACTIONS, buyVehicle, scrapVehicle, getStation } from '../game/state.js';

const CLASS_ICONS = {
  [VEHICLE_CLASSES.TRAIN]: '🚂',
  [VEHICLE_CLASSES.ROAD]: '🚌',
  [VEHICLE_CLASSES.AIR]: '✈️',
  [VEHICLE_CLASSES.WATER]: '🚢',
};

export default function VehiclePanel({ state, dispatch, onClose }) {
  const [tab, setTab] = useState('buy'); // buy, manage, route

  const gs = state.gameState;
  const currentYear = gs.date.getFullYear();

  // Gather all stations (stations + docks + airports)
  const allStations = [...(gs.stations || []), ...(gs.docks || []), ...(gs.airports || [])];

  const vehiclesByClass = {};
  VEHICLE_DEFS.forEach(v => {
    if (!vehiclesByClass[v.cls]) vehiclesByClass[v.cls] = [];
    if (v.minYear <= currentYear) vehiclesByClass[v.cls].push(v);
  });

  const handleBuy = (defId) => {
    const stations = [...(gs.stations || []), ...(gs.docks || []), ...(gs.airports || [])];
    if (stations.length === 0) {
      dispatch({ type: ACTIONS.CLEAR_NOTIFICATIONS });
      return;
    }
    const def = VEHICLE_DEFS[defId];
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
    const newState = buyVehicle(gs, defId, station.id);
    if (newState !== gs) {
      dispatch({ type: 'UPDATE_GAME_STATE', payload: newState });
    }
  };

  const handleScrap = (vehicleId) => {
    const newState = scrapVehicle(gs, vehicleId);
    if (newState !== gs) {
      dispatch({ type: 'UPDATE_GAME_STATE', payload: newState });
    }
  };

  const handleSetRoute = (vehicleId) => {
    const vehicle = gs.vehicles.find(v => v.id === vehicleId);
    if (!vehicle) return;
    // Enter route mode with the vehicle's current route as starting stops
    const currentStops = vehicle.route || [];
    dispatch({ type: 'ENTER_ROUTE_MODE', payload: { vehicleId, stations: currentStops } });
    setTab('route');
  };

  const handleApplyRoute = () => {
    dispatch({ type: 'APPLY_ROUTE' });
    setTab('manage');
  };

  const handleCancelRoute = () => {
    dispatch({ type: 'CANCEL_ROUTE' });
    setTab('manage');
  };

  const handleRemoveStop = (stationId) => {
    dispatch({ type: 'REMOVE_ROUTE_STOP', payload: { stationId } });
  };

  const routeVehicle = gs.routeMode ? gs.vehicles.find(v => v.id === gs.routeMode.vehicleId) : null;

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
                  const cost = Math.floor(def.cost * gs.costMult);
                  const canAfford = gs.money >= cost;
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
          {(!gs.stations || gs.stations.length === 0) && (!gs.docks || gs.docks.length === 0) && (!gs.airports || gs.airports.length === 0) && (
            <div style={{ padding: '12px', background: 'rgba(231,76,60,0.2)', borderRadius: '4px', color: '#e74c3c' }}>
              ⚠️ Build a station first! You need a station to buy vehicles.
            </div>
          )}
        </div>
      )}

      {tab === 'manage' && (
        <div>
          {gs.vehicles.length === 0 ? (
            <div style={{ color: '#888', textAlign: 'center', padding: '20px' }}>
              No vehicles yet. Buy one from the "Buy New" tab!
            </div>
          ) : (
            gs.vehicles.map(v => {
              const def = VEHICLE_DEFS[v.defId];
              if (!def) return null;
              const cargoTotal = v.cargo.reduce((s, c) => s + c.amount, 0);
              return (
                <div
                  key={v.id}
                  className={`vehicle-item ${gs.selectedVehicle === v.id ? 'selected' : ''}`}
                  onClick={() => dispatch({ type: ACTIONS.SELECT_VEHICLE, payload: v.id })}
                >
                  <div className="vehicle-color" style={{ background: def.color }} />
                  <div className="vehicle-info">
                    <div className="vehicle-name">{def.name} #{v.id + 1}</div>
                    <div className="vehicle-detail">
                      {v.brokenDown ? '⚠️ Broken Down' : v.state === 'moving' ? '🚀 Moving' :
                       v.state === 'loading' ? '📦 Loading' : v.state === 'unloading' ? '📤 Unloading' : '⏸ Idle'}
                      {cargoTotal > 0 && ` | ${cargoTotal} cargo`}
                      {v.route.length > 0 && ` | Route: ${v.route.length} stops`}
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: '4px' }}>
                    <button
                      className="btn"
                      style={{ padding: '4px 8px', fontSize: '11px' }}
                      onClick={(e) => { e.stopPropagation(); handleSetRoute(v.id); }}
                    >
                      Route
                    </button>
                    <button
                      className="btn btn-danger"
                      style={{ padding: '4px 8px', fontSize: '11px' }}
                      onClick={(e) => { e.stopPropagation(); handleScrap(v.id); }}
                    >
                      Scrap
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>
      )}

      {tab === 'route' && gs.routeMode && (
        <div>
          <div style={{ background: 'rgba(74,122,170,0.2)', padding: '10px', borderRadius: '4px', marginBottom: '12px' }}>
            <strong>📍 Setting route for {routeVehicle ? VEHICLE_DEFS[routeVehicle.defId]?.name : 'Unknown'} #{(gs.routeMode.vehicleId || 0) + 1}</strong>
            <p style={{ fontSize: '12px', color: '#aaa', margin: '6px 0 0' }}>
              Click stations on the map to add them to this route. Need at least 2 stops.
            </p>
          </div>

          <h4 style={{ color: '#4a7aaa', fontSize: '13px', marginBottom: '8px' }}>
            Route Stops ({gs.routeMode.stations.length})
          </h4>

          {gs.routeMode.stations.length === 0 ? (
            <div style={{ color: '#888', fontSize: '12px', textAlign: 'center', padding: '12px' }}>
              Click stations on the map to add stops...
            </div>
          ) : (
            <div style={{ marginBottom: '12px' }}>
              {gs.routeMode.stations.map((stationId, idx) => {
                const station = getStation(gs, stationId);
                if (!station) return null;
                return (
                  <div key={`${stationId}-${idx}`} style={{
                    display: 'flex', alignItems: 'center', gap: '8px',
                    padding: '6px 8px', background: 'rgba(255,255,255,0.05)', borderRadius: '4px',
                    marginBottom: '4px'
                  }}>
                    <span style={{ color: '#4a7aaa', fontWeight: 'bold', minWidth: '20px' }}>#{idx + 1}</span>
                    <span style={{ flex: 1, fontSize: '12px' }}>
                      {station.type === 3 ? '🚉' : station.type === 4 ? '🚌' : station.type === 5 ? '🚛' : station.type === 6 ? '✈️' : '🚢'}
                      {' '}{station.name}
                    </span>
                    <button
                      className="btn btn-danger"
                      style={{ padding: '2px 6px', fontSize: '10px' }}
                      onClick={() => handleRemoveStop(stationId)}
                    >
                      ✕
                    </button>
                  </div>
                );
              })}
            </div>
          )}

          <div style={{ display: 'flex', gap: '8px' }}>
            <button className="btn btn-success" onClick={handleApplyRoute}
              disabled={gs.routeMode.stations.length < 2}
              style={{ flex: 1, opacity: gs.routeMode.stations.length < 2 ? 0.5 : 1 }}>
              ✓ Apply Route
            </button>
            <button className="btn btn-danger" onClick={handleCancelRoute} style={{ flex: 1 }}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
