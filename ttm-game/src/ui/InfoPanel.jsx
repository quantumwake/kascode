// ===== INFO PANEL =====

import React from 'react';
import { MAP_SIZE, TERRAIN, TERRAIN_NAMES, TILE, SURFACE_COLORS, VEHICLE_DEFS, INDUSTRY_TYPES } from '../game/constants.js';

export default function InfoPanel({ state, onClose }) {
  if (!state.hoveredTile) {
    return (
      <div className="panel" style={{ minWidth: '350px' }}>
        <button className="panel-close" onClick={onClose}>✕</button>
        <h2>📋 Info</h2>
        <div style={{ color: '#888', textAlign: 'center', padding: '20px' }}>
          Hover over the map to see details
        </div>
      </div>
    );
  }

  const { x, y } = state.hoveredTile;
  const idx = y * MAP_SIZE + x;
  const terrain = state.terrain[idx];
  const surface = state.surface[idx];
  const feature = state.features[idx];

  // Find town
  const town = state.towns.find(t => Math.hypot(t.x - x, t.y - y) < 20);
  // Find industry
  const industry = state.industries.find(i => Math.hypot(i.x - x, i.y - y) < 10);
  // Find vehicle
  const vehicle = state.vehicles.find(v => v.x === x && v.y === y);

  return (
    <div className="panel" style={{ minWidth: '350px' }}>
      <button className="panel-close" onClick={onClose}>✕</button>
      <h2>📋 Tile Info</h2>

      <div style={{ fontSize: '13px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
          <span className="label">Position:</span>
          <span>{x}, {y}</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
          <span className="label">Terrain:</span>
          <span>{TERRAIN_NAMES[terrain] || 'Unknown'}</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
          <span className="label">Surface:</span>
          <span>{Object.entries(TILE).find(([, v]) => v === surface)?.[0] || 'None'}</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
          <span className="label">Feature:</span>
          <span>{feature === 1 ? 'Tree' : feature === 2 ? 'House' : feature === 3 ? 'Industry' : 'None'}</span>
        </div>

        {town && (
          <div style={{ marginTop: '12px', padding: '8px', background: 'rgba(46,139,87,0.2)', borderRadius: '4px' }}>
            <div style={{ fontWeight: 'bold', color: '#2ecc71' }}>{town.name}</div>
            <div className="vehicle-detail">
              Population: {town.population} | Service: {town.serviceRating}%
            </div>
            <div className="vehicle-detail">
              Passengers waiting: {town.passengersWaiting}
            </div>
          </div>
        )}

        {industry && (
          <div style={{ marginTop: '12px', padding: '8px', background: 'rgba(186,85,85,0.2)', borderRadius: '4px' }}>
            <div style={{ fontWeight: 'bold', color: '#e74c3c' }}>{industry.name}</div>
            <div className="vehicle-detail">
              Producing: {industry.producesCargoId !== undefined ? true : false} | Storage: {industry.storage}/{industry.maxStorage}
            </div>
          </div>
        )}

        {vehicle && (
          <div style={{ marginTop: '12px', padding: '8px', background: 'rgba(74,122,170,0.2)', borderRadius: '4px' }}>
            <div style={{ fontWeight: 'bold', color: '#4a7aaa' }}>
              {VEHICLE_DEFS[vehicle.defId]?.name || 'Unknown'} #{vehicle.id + 1}
            </div>
            <div className="vehicle-detail">
              State: {vehicle.brokenDown ? 'Broken Down' : vehicle.state}
            </div>
            <div className="vehicle-detail">
              Cargo: {vehicle.cargo.reduce((s, c) => s + c.amount, 0)} units
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
