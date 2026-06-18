// ===== SAVE/LOAD PANEL =====

import React, { useState, useEffect } from 'react';
import { getSavedGames, deleteSave, saveGame, saveGameAsFile, loadGame } from '../game/saveLoad.js';
import { ACTIONS } from '../game/state.js';

export default function SaveLoadPanel({ state, dispatch, onClose, onLoadGame, onLoadFile, onSave }) {
  const [saves, setSaves] = useState([]);
  const [saveName, setSaveName] = useState('');

  useEffect(() => {
    setSaves(getSavedGames());
  }, []);

  const handleSave = () => {
    if (!saveName.trim()) return;
    saveGame(state, saveName.trim());
    setSaves(getSavedGames());
    setSaveName('');
    onSave();
  };

  const handleSaveAsFile = () => {
    if (!saveName.trim()) return;
    saveGameAsFile(state, saveName.trim());
    setSaveName('');
  };

  const handleLoad = (saveData) => {
    onLoadGame(saveData);
    onClose();
  };

  const handleDelete = (name) => {
    deleteSave(name);
    setSaves(getSavedGames());
  };

  const handleFileInput = (e) => {
    onLoadFile(e);
    onClose();
  };

  return (
    <div className="panel" style={{ minWidth: '450px' }}>
      <button className="panel-close" onClick={onClose}>✕</button>
      <h2>💾 Save / Load</h2>

      {/* Save section */}
      <div style={{ marginBottom: '16px' }}>
        <div className="label" style={{ marginBottom: '8px' }}>Save Game</div>
        <div style={{ display: 'flex', gap: '8px' }}>
          <input
            type="text"
            value={saveName}
            onChange={e => setSaveName(e.target.value)}
            placeholder="Save name..."
            style={{ flex: 1 }}
          />
          <button className="btn btn-success" onClick={handleSave}>Save</button>
          <button className="btn" onClick={handleSaveAsFile}>Export</button>
        </div>
        <button className="btn" onClick={onSave} style={{ marginTop: '6px' }}>
          Quick Save (Slot 1)
        </button>
      </div>

      {/* Load section */}
      <div style={{ marginBottom: '16px' }}>
        <div className="label" style={{ marginBottom: '8px' }}>Load Game</div>
        <div style={{ display: 'flex', gap: '8px', marginBottom: '8px' }}>
          <button className="btn" onClick={() => {
            const input = document.createElement('input');
            input.type = 'file';
            input.accept = '.json';
            input.onchange = handleFileInput;
            input.click();
          }}>
            📂 Import from File
          </button>
        </div>

        <div className="label" style={{ marginBottom: '6px' }}>Saved Games</div>
        {saves.length === 0 ? (
          <div style={{ color: '#666', padding: '12px', textAlign: 'center' }}>
            No saved games found
          </div>
        ) : (
          saves.map((save, i) => (
            <div key={i} className="save-item">
              <div className="save-info">
                <div className="save-name">{save.name}</div>
                <div className="save-date">
                  {new Date(save.date).toLocaleDateString()} | ${save.money?.toLocaleString() || '0'}
                </div>
              </div>
              <button className="btn" style={{ marginRight: '4px' }} onClick={() => handleLoad(save)}>
                Load
              </button>
              <button className="btn btn-danger" style={{ padding: '4px 8px', fontSize: '11px' }} onClick={() => handleDelete(save.name)}>
                ✕
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
