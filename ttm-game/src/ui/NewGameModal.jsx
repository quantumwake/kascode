// ===== NEW GAME MODAL / TITLE SCREEN =====

import React, { useState, useEffect } from 'react';
import { getSavedGames, loadGame, loadGameFromFile } from '../game/saveLoad.js';

export default function NewGameModal({ onNewGame, onLoadGame, onLoadFile }) {
  const [seed, setSeed] = useState(String(Math.floor(Math.random() * 99999)));
  const [difficulty, setDifficulty] = useState('normal');
  const [step, setStep] = useState('title'); // title, newgame, load
  const [saves, setSaves] = useState([]);

  useEffect(() => {
    setSaves(getSavedGames());
  }, []);

  const difficulties = [
    { key: 'easy', name: 'Easy', desc: '$200K start, lower costs' },
    { key: 'normal', name: 'Normal', desc: '$100K start, standard' },
    { key: 'hard', name: 'Hard', desc: '$50K start, higher costs' },
  ];

  const handleNewGame = () => {
    onNewGame(parseInt(seed) || Math.floor(Math.random() * 99999), difficulty);
  };

  const handleLoad = (saveData) => {
    onLoadGame(saveData);
  };

  const handleFileLoad = (e) => {
    onLoadFile(e);
  };

  if (step === 'title') {
    return (
      <div className="title-screen">
        <h1>🚂 Transport Tycoon Remake</h1>
        <div className="subtitle">Build networks. Transport cargo. Make money.</div>

        <button className="btn title-btn" onClick={() => setStep('newgame')}>
          🎮 New Game
        </button>
        <button className="btn title-btn" onClick={() => setStep('load')}>
          📁 Load Game
        </button>
        <button className="btn title-btn" onClick={() => {
          const input = document.createElement('input');
          input.type = 'file';
          input.accept = '.json';
          input.onchange = handleFileLoad;
          input.click();
        }}>
          📂 Import Save
        </button>

        <div style={{ marginTop: '40px', color: '#667', fontSize: '12px', textAlign: 'center' }}>
          <p>Arrow Keys / WASD: Move camera | Space: Pause | Esc: Close panels</p>
          <p>1-9: Select tools | Scroll: Zoom | Click: Build/Interact</p>
        </div>
      </div>
    );
  }

  if (step === 'newgame') {
    return (
      <div className="title-screen">
        <h1 style={{ fontSize: '32px' }}>🎮 New Game</h1>

        <div style={{ maxWidth: '400px', width: '100%' }}>
          <div className="form-group">
            <label>Map Seed</label>
            <input
              type="text"
              value={seed}
              onChange={e => setSeed(e.target.value)}
              placeholder="Random map seed..."
            />
            <div style={{ fontSize: '11px', color: '#667', marginTop: '4px' }}>
              Different seeds create different maps. Leave blank for random.
            </div>
          </div>

          <div className="form-group">
            <label>Difficulty</label>
            <div className="grid-3">
              {difficulties.map(d => (
                <button
                  key={d.key}
                  className={`btn ${difficulty === d.key ? 'active' : ''}`}
                  onClick={() => setDifficulty(d.key)}
                  style={{ textAlign: 'center' }}
                >
                  <div style={{ fontWeight: 'bold' }}>{d.name}</div>
                  <div style={{ fontSize: '11px', color: '#8899aa' }}>{d.desc}</div>
                </button>
              ))}
            </div>
          </div>

          <div style={{ display: 'flex', gap: '12px', marginTop: '20px' }}>
            <button className="btn btn-success title-btn" onClick={handleNewGame}>
              Start Game
            </button>
            <button className="btn title-btn" onClick={() => setStep('title')}>
              Back
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (step === 'load') {
    return (
      <div className="title-screen">
        <h1 style={{ fontSize: '32px' }}>📁 Load Game</h1>

        <div style={{ maxWidth: '500px', width: '100%' }}>
          <button className="btn title-btn" style={{ marginBottom: '12px' }} onClick={() => {
            const input = document.createElement('input');
            input.type = 'file';
            input.accept = '.json';
            input.onchange = handleFileLoad;
            input.click();
          }}>
            📂 Import from File
          </button>

          <div className="label" style={{ marginBottom: '8px' }}>Saved Games</div>
          {saves.length === 0 ? (
            <div style={{ color: '#666', padding: '20px', textAlign: 'center' }}>
              No saved games found
            </div>
          ) : (
            saves.map((save, i) => (
              <div key={i} className="save-item" onClick={() => handleLoad(save)}>
                <div className="save-info">
                  <div className="save-name">{save.name}</div>
                  <div className="save-date">
                    {new Date(save.date).toLocaleDateString()} | ${save.money?.toLocaleString() || '0'}
                  </div>
                </div>
                <span style={{ color: '#4a7aaa' }}>▶ Load</span>
              </div>
            ))
          )}

          <button className="btn title-btn" onClick={() => setStep('title')} style={{ marginTop: '12px' }}>
            Back
          </button>
        </div>
      </div>
    );
  }

  return null;
}
