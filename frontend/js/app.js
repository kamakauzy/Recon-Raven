/**
 * Recon-Raven Dashboard — main application controller.
 */
(function() {
  'use strict';

  const API = '/api';
  let wsAlerts = null;
  let wsSpectrum = null;
  let wsStatus = null;
  let activeCapture = null;

  // ── Tab Navigation ──────────────────────────────────────
  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
      tab.classList.add('active');
      document.getElementById('tab-' + tab.dataset.tab).classList.add('active');
      // Init + fix Leaflet map after browser layout completes
      if (tab.dataset.tab === 'map' && window.RavenMap) {
        requestAnimationFrame(() => requestAnimationFrame(() => {
          window.RavenMap.init();
        }));
      }
    });
  });

  // ── Clock ───────────────────────────────────────────────
  function updateClock() {
    const now = new Date();
    document.getElementById('clock').textContent =
      now.toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
  }
  setInterval(updateClock, 1000);
  updateClock();

  // ── API Helpers ─────────────────────────────────────────
  async function api(path, opts) {
    const res = await fetch(API + path, opts);
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || res.statusText);
    }
    return res.json();
  }

  // ── WebSocket ───────────────────────────────────────────
  function connectWS(path, onMessage) {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = proto + '//' + location.host + path;
    const ws = new WebSocket(url);

    ws.onopen = () => {
      console.log('WS connected:', path);
      updateWSIndicator(true);
    };
    ws.onmessage = (e) => {
      try { onMessage(JSON.parse(e.data)); } catch(err) { console.error(err); }
    };
    ws.onclose = () => {
      updateWSIndicator(false);
      setTimeout(() => connectWS(path, onMessage), 3000);
    };
    ws.onerror = () => ws.close();
    return ws;
  }

  function updateWSIndicator(connected) {
    const el = document.getElementById('ws-indicator');
    el.classList.toggle('on', connected);
    el.classList.toggle('off', !connected);
  }

  // ── Devices ─────────────────────────────────────────────
  async function loadDevices() {
    try {
      const devices = await api('/devices');
      const grid = document.getElementById('device-cards');
      grid.innerHTML = '';

      if (devices.length === 0) {
        grid.innerHTML = '<p class="placeholder">No SDR devices detected</p>';
      }

      devices.forEach(d => {
        const card = document.createElement('div');
        card.className = 'card';
        card.innerHTML = `
          <h3>${d.device_type === 'hackrf' ? '📡' : '📻'} ${d.model || 'Unknown'}</h3>
          <div class="status ${d.status}">${d.status.toUpperCase()}</div>
          <div style="font-size:12px; color:var(--text-dim); margin-top:6px;">
            Index: ${d.sdr_index} &bull; Serial: ${d.serial || 'N/A'}
            ${d.assigned_task ? '<br>Task: ' + d.assigned_task : ''}
          </div>
        `;
        grid.appendChild(card);
      });

      // Populate spectrum SDR selector
      const sel = document.getElementById('spectrum-sdr');
      sel.innerHTML = '';
      devices.filter(d => d.device_type === 'rtlsdr').forEach(d => {
        const opt = document.createElement('option');
        opt.value = d.sdr_index;
        opt.textContent = `SDR ${d.sdr_index} (${d.model})`;
        sel.appendChild(opt);
      });

    } catch (e) {
      console.error('Failed to load devices:', e);
    }
  }

  async function loadGPS() {
    try {
      const gps = await api('/gps/current');
      const el = document.getElementById('gps-detail');
      const ind = document.getElementById('gps-indicator');

      if (gps.has_fix) {
        ind.classList.add('on'); ind.classList.remove('off');
        el.innerHTML = `
          <div>Lat: ${gps.latitude.toFixed(6)} &bull; Lon: ${gps.longitude.toFixed(6)}</div>
          <div style="font-size:12px; color:var(--text-dim)">
            Alt: ${gps.altitude_m ? gps.altitude_m.toFixed(1) + 'm' : 'N/A'} &bull;
            Sats: ${gps.satellites || 'N/A'} &bull;
            Error: ${gps.error_m ? gps.error_m.toFixed(1) + 'm' : 'N/A'}
          </div>
        `;
      } else {
        ind.classList.remove('on'); ind.classList.add('off');
        el.innerHTML = '<span class="placeholder">No GPS fix</span>';
      }
    } catch (e) {
      document.getElementById('gps-detail').innerHTML = '<span class="placeholder">GPS unavailable</span>';
    }
  }

  document.getElementById('btn-enumerate').addEventListener('click', async () => {
    await api('/devices/enumerate', { method: 'POST' });
    await loadDevices();
  });

  // ── Alerts ──────────────────────────────────────────────
  let alertCount = 0;

  function addAlertItem(data) {
    const feed = document.getElementById('alert-feed');
    const item = document.createElement('div');
    item.className = 'feed-item';

    const type = data.type || data.event_type || 'event';
    const freq = data.freq_mhz || data.freq || '';
    const power = data.peak_power_db || data.power_db || '';
    const dur = data.duration_ms || '';
    const time = data.timestamp || new Date().toISOString();

    item.innerHTML = `
      <span class="time">${time.replace('T', ' ').slice(11, 19)}</span>
      <span class="type ${type}">${type}</span>
      <span class="freq">${freq ? freq + ' MHz' : ''}</span>
      <span class="power">${power ? power + ' dB' : ''}</span>
      <span>${dur ? dur + ' ms' : ''}</span>
    `;

    feed.insertBefore(item, feed.firstChild);
    alertCount++;
    document.getElementById('alert-count').textContent = alertCount + ' events';

    // Cap at 500 items
    while (feed.children.length > 500) {
      feed.removeChild(feed.lastChild);
    }
  }

  async function loadEventHistory() {
    try {
      const events = await api('/events?limit=100');
      events.reverse().forEach(e => addAlertItem(e));
    } catch (e) {
      console.error('Failed to load events:', e);
    }
  }

  // ── Baselines ───────────────────────────────────────────
  async function loadBaselines() {
    try {
      const baselines = await api('/baselines');
      const list = document.getElementById('baseline-list');
      list.innerHTML = '';

      if (baselines.length === 0) {
        list.innerHTML = '<p class="placeholder">No baselines captured yet</p>';
        return;
      }

      baselines.forEach(b => {
        const item = document.createElement('div');
        item.className = 'list-item';
        item.innerHTML = `
          <span>${b.timestamp.replace('T', ' ').slice(0, 19)}</span>
          <span>${b.device_count} devices &bull; ${b.duration_s}s</span>
        `;
        item.addEventListener('click', () => loadDiff(b.id));
        list.appendChild(item);
      });
    } catch (e) {
      console.error('Failed to load baselines:', e);
    }
  }

  async function loadDiff(baselineId) {
    try {
      const diff = await api('/baselines/' + baselineId + '/diff');
      document.getElementById('diff-content').textContent = diff.report_text;
      document.getElementById('baseline-diff').style.display = 'block';
    } catch (e) {
      document.getElementById('baseline-diff').style.display = 'none';
    }
  }

  // ── Reports ─────────────────────────────────────────────
  async function loadReports() {
    try {
      const reports = await api('/reports');
      const list = document.getElementById('report-list');
      list.innerHTML = '';

      if (reports.length === 0) {
        list.innerHTML = '<p class="placeholder">No reports generated yet</p>';
        return;
      }

      reports.forEach(r => {
        const item = document.createElement('div');
        item.className = 'list-item';
        item.innerHTML = `
          <span>${r.title || 'Intel Report'}</span>
          <span>${r.timestamp.replace('T', ' ').slice(0, 19)} &bull; ${r.event_count} events</span>
        `;
        item.addEventListener('click', () => loadReport(r.id));
        list.appendChild(item);
      });
    } catch (e) {
      console.error('Failed to load reports:', e);
    }
  }

  async function loadReport(reportId) {
    try {
      const report = await api('/reports/' + reportId);
      document.getElementById('report-content').innerHTML = report.content
        .replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/^(#+)\s(.*)$/gm, (m, h, t) => `<h${h.length}>${t}</h${h.length}>`)
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\n/g, '<br>');
      document.getElementById('report-viewer').style.display = 'block';
    } catch (e) {
      console.error('Failed to load report:', e);
    }
  }


  // ── Report Generation ───────────────────────────────────
  document.getElementById('btn-generate-report').addEventListener('click', async () => {
    const btn = document.getElementById('btn-generate-report');
    btn.disabled = true;
    btn.textContent = 'Generating...';
    try {
      const result = await api('/reports/generate', { method: 'POST' });
      await loadReports();
      if (result && result.id) {
        loadReport(result.id);
      }
    } catch (e) {
      console.error('Report generation failed:', e);
      alert('Report generation failed: ' + e.message);
    } finally {
      btn.disabled = false;
      btn.textContent = 'Generate Now';
    }
  });

  // ── Spectrum Controls ───────────────────────────────────
  document.getElementById('spectrum-gain').addEventListener('input', (e) => {
    document.getElementById('spectrum-gain-val').textContent = e.target.value;
  });

  document.getElementById('spectrum-start').addEventListener('click', async () => {
    const sdr = document.getElementById('spectrum-sdr').value;
    const low = parseFloat(document.getElementById('spectrum-low').value);
    const high = parseFloat(document.getElementById('spectrum-high').value);
    const gain = parseInt(document.getElementById('spectrum-gain').value);

    try {
      const result = await api('/captures/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          task_type: 'power_sweep',
          sdr_index: parseInt(sdr),
          freq_mhz: (low + high) / 2,
          freq_low: low,
          freq_high: high,
          gain: gain,
          duration: 0,
        }),
      });
      activeCapture = result.task_id;
      document.getElementById('spectrum-start').disabled = true;
      document.getElementById('spectrum-stop').disabled = false;
      document.getElementById('spectrum-status').textContent =
        `Running: ${result.task_type} on SDR ${sdr} (${low}-${high} MHz)`;
    } catch (e) {
      alert('Failed to start: ' + e.message);
    }
  });

  document.getElementById('spectrum-stop').addEventListener('click', async () => {
    if (activeCapture) {
      await api('/captures/' + activeCapture + '/stop', { method: 'POST' });
      activeCapture = null;
      document.getElementById('spectrum-start').disabled = false;
      document.getElementById('spectrum-stop').disabled = true;
      document.getElementById('spectrum-status').textContent = 'Idle';
    }
  });

  // ── Classifier ──────────────────────────────────────────
  async function loadClassifierRules() {
    try {
      const rules = await api('/classifier/rules');
      const el = document.getElementById('classifier-rules');
      el.innerHTML = '';
      if (!rules.length) {
        el.innerHTML = '<p class="placeholder">No rules loaded</p>';
        return;
      }
      rules.forEach(r => {
        const item = document.createElement('div');
        item.className = 'list-item';
        item.innerHTML = `
          <span><strong>${r.name}</strong> — ${r.description || ''}</span>
          <span style="font-size:11px;color:var(--text-dim)">Priority: ${r.priority} &bull; Models: ${(r.models || []).length}</span>
        `;
        el.appendChild(item);
      });
    } catch (e) {
      console.error('Failed to load classifier rules:', e);
    }
  }

  document.getElementById('btn-classify').addEventListener('click', async () => {
    const resultEl = document.getElementById('cls-result');
    try {
      const result = await api('/classifier/classify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          freq_mhz: parseFloat(document.getElementById('cls-freq').value),
          duration_ms: parseFloat(document.getElementById('cls-duration').value),
          modulation: document.getElementById('cls-mod').value,
          model: document.getElementById('cls-model').value,
        }),
      });
      resultEl.style.display = 'block';
      if (result.label && result.label !== 'Unknown') {
        resultEl.style.color = 'var(--green)';
        resultEl.textContent = `✓ ${result.label} (${(result.confidence * 100).toFixed(0)}% confidence) — Rule: ${result.rule || 'ML'}`;
      } else {
        resultEl.style.color = 'var(--yellow)';
        resultEl.textContent = '? Unknown — no matching rule';
      }
    } catch (e) {
      resultEl.style.display = 'block';
      resultEl.style.color = 'var(--red)';
      resultEl.textContent = 'Error: ' + e.message;
    }
  });

  // ── Direction Finding ───────────────────────────────────
  document.getElementById('btn-add-bearing').addEventListener('click', () => {
    const container = document.getElementById('df-bearings');
    const row = document.createElement('div');
    row.className = 'df-bearing-row controls';
    row.style.marginBottom = '6px';
    row.innerHTML = `
      <label>Lat: <input type="number" class="df-lat" step="0.0001" style="width:100px;"></label>
      <label>Lon: <input type="number" class="df-lon" step="0.0001" style="width:100px;"></label>
      <label>Bearing: <input type="number" class="df-bearing" step="0.1" style="width:80px;"> °</label>
      <button class="btn btn-red" style="padding:2px 8px;" onclick="this.parentElement.remove()">×</button>
    `;
    container.appendChild(row);
  });

  document.getElementById('btn-use-gps').addEventListener('click', async () => {
    try {
      const gps = await api('/gps/current');
      if (gps.has_fix) {
        const rows = document.querySelectorAll('.df-bearing-row');
        const last = rows[rows.length - 1];
        if (last) {
          last.querySelector('.df-lat').value = gps.latitude.toFixed(6);
          last.querySelector('.df-lon').value = gps.longitude.toFixed(6);
        }
      } else {
        alert('No GPS fix available');
      }
    } catch (e) {
      alert('GPS error: ' + e.message);
    }
  });

  document.getElementById('btn-solve-df').addEventListener('click', async () => {
    const rows = document.querySelectorAll('.df-bearing-row');
    const measurements = [];
    rows.forEach(row => {
      const lat = parseFloat(row.querySelector('.df-lat').value);
      const lon = parseFloat(row.querySelector('.df-lon').value);
      const bearing = parseFloat(row.querySelector('.df-bearing').value);
      if (!isNaN(lat) && !isNaN(lon) && !isNaN(bearing)) {
        measurements.push({ latitude: lat, longitude: lon, bearing_deg: bearing });
      }
    });

    if (measurements.length < 2) {
      alert('Need at least 2 bearings with valid lat/lon');
      return;
    }

    try {
      const result = await api('/df/solve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ measurements }),
      });
      const el = document.getElementById('df-result');
      el.style.display = 'block';
      document.getElementById('df-result-detail').innerHTML = `
        <div style="font-size:14px; margin-bottom:8px;">
          <strong style="color:var(--green);">📍 ${result.latitude.toFixed(6)}, ${result.longitude.toFixed(6)}</strong>
        </div>
        <div style="font-size:12px; color:var(--text-dim);">
          CEP: ${result.cep_m}m &bull; Bearings: ${result.num_bearings} &bull; Residual: ${result.residual}
        </div>
        <div style="margin-top:8px;">
          <a href="https://www.google.com/maps?q=${result.latitude},${result.longitude}" target="_blank"
             style="color:var(--accent); font-size:12px;">Open in Google Maps ↗</a>
        </div>
      `;
    } catch (e) {
      alert('DF solve error: ' + e.message);
    }
  });

  // ── FISSURE ─────────────────────────────────────────────
  async function loadFissureStatus() {
    try {
      const status = await api('/fissure/status');
      const badge = document.getElementById('fissure-status-badge');
      if (status.available) {
        badge.textContent = `${status.protocol_count} PROTOCOLS`;
        badge.className = 'badge live';
      } else {
        badge.textContent = 'NOT INSTALLED';
        badge.className = 'badge off';
      }
    } catch (e) {
      document.getElementById('fissure-status-badge').textContent = 'ERROR';
    }
  }

  document.getElementById('btn-fissure-query').addEventListener('click', async () => {
    const freq = parseFloat(document.getElementById('fissure-freq').value);
    const mod = document.getElementById('fissure-mod').value;
    try {
      const results = await api(`/fissure/protocols/query?freq=${freq}&modulation=${encodeURIComponent(mod)}`);
      const el = document.getElementById('fissure-results');
      el.innerHTML = '';
      if (!results.length) {
        el.innerHTML = '<p class="placeholder">No matching protocols found</p>';
        return;
      }
      results.forEach(p => {
        const item = document.createElement('div');
        item.className = 'list-item';
        item.style.flexDirection = 'column';
        item.style.alignItems = 'flex-start';
        item.innerHTML = `
          <div><strong>${p.protocol || p.name || 'Unknown'}</strong></div>
          <div style="font-size:11px;color:var(--text-dim);">
            ${p.modulation || ''} &bull; ${p.frequency || p.freq || ''} MHz
            ${p.bandwidth ? '&bull; BW: ' + p.bandwidth : ''}
          </div>
        `;
        el.appendChild(item);
      });
    } catch (e) {
      document.getElementById('fissure-results').innerHTML =
        '<p class="placeholder" style="color:var(--red);">Query failed: ' + e.message + '</p>';
    }
  });

  document.getElementById('btn-fissure-launch').addEventListener('click', async () => {
    try {
      await api('/fissure/launch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ freq_mhz: parseFloat(document.getElementById('fissure-freq').value) }),
      });
    } catch (e) {
      alert('FISSURE launch error: ' + e.message);
    }
  });

  // ── TX ──────────────────────────────────────────────────
  async function loadTXStatus() {
    try {
      const status = await api('/tx/status');
      const masterBadge = document.getElementById('tx-master');
      const enabledBadge = document.getElementById('tx-enabled');
      const transmitBtn = document.getElementById('btn-tx-transmit');

      if (status.enabled) {
        masterBadge.textContent = 'TX ENABLED';
        masterBadge.className = 'badge live';
        enabledBadge.textContent = 'ON';
        enabledBadge.className = 'badge live';
        transmitBtn.disabled = false;
      } else {
        masterBadge.textContent = 'TX DISABLED';
        masterBadge.className = 'badge off';
        enabledBadge.textContent = 'OFF';
        enabledBadge.className = 'badge off';
        transmitBtn.disabled = true;
      }

      document.getElementById('tx-max-gain').textContent = status.max_gain_db || 30;
      document.getElementById('tx-max-dur').textContent = status.max_duration_s || 30;

      if (status.authorized_bands) {
        document.getElementById('tx-bands').textContent = 'Authorized bands: ' +
          status.authorized_bands.map(b => `${b.low_mhz}–${b.high_mhz} MHz`).join(', ');
      }
    } catch (e) {
      console.error('TX status error:', e);
    }
  }

  document.getElementById('tx-gain').addEventListener('input', (e) => {
    document.getElementById('tx-gain-val').textContent = e.target.value;
  });

  document.getElementById('btn-tx-enable').addEventListener('click', async () => {
    if (!confirm('⚠️ LEGAL WARNING: Enabling TX allows RF transmission. Unauthorized transmission is a federal crime. Continue?')) return;
    try {
      await api('/tx/enable', { method: 'POST' });
      await loadTXStatus();
    } catch (e) { alert('TX enable error: ' + e.message); }
  });

  document.getElementById('btn-tx-disable').addEventListener('click', async () => {
    try {
      await api('/tx/disable', { method: 'POST' });
      await loadTXStatus();
    } catch (e) { alert('TX disable error: ' + e.message); }
  });

  document.getElementById('btn-tx-transmit').addEventListener('click', async () => {
    const freq = parseFloat(document.getElementById('tx-freq').value);
    const gain = parseInt(document.getElementById('tx-gain').value);
    const dur = parseInt(document.getElementById('tx-dur').value);
    const txType = document.getElementById('tx-type').value;

    if (!confirm(`Transmit ${txType} on ${freq} MHz at ${gain} dB for ${dur}s?`)) return;

    const resultEl = document.getElementById('tx-result');
    try {
      const result = await api('/tx/transmit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          freq_mhz: freq,
          gain_db: gain,
          duration_s: dur,
          tx_type: txType,
        }),
      });
      resultEl.style.display = 'block';
      resultEl.style.color = 'var(--green)';
      resultEl.textContent = `✓ TX started: ${txType} on ${freq} MHz`;
    } catch (e) {
      resultEl.style.display = 'block';
      resultEl.style.color = 'var(--red)';
      resultEl.textContent = '✗ ' + e.message;
    }
  });

  document.getElementById('btn-tx-stop').addEventListener('click', async () => {
    try {
      await api('/tx/stop', { method: 'POST' });
      document.getElementById('tx-result').style.display = 'block';
      document.getElementById('tx-result').style.color = 'var(--yellow)';
      document.getElementById('tx-result').textContent = 'TX stopped';
    } catch (e) { alert('TX stop error: ' + e.message); }
  });

  // ── Federation ──────────────────────────────────────────
  async function loadFederationStatus() {
    try {
      const status = await api('/federation/status');
      const badge = document.getElementById('fed-status-badge');

      if (status.running) {
        badge.textContent = `${status.peer_count} PEERS`;
        badge.className = 'badge live';
      } else if (status.enabled) {
        badge.textContent = 'STARTING';
        badge.className = 'badge off';
      } else {
        badge.textContent = 'DISABLED';
        badge.className = 'badge off';
      }

      document.getElementById('fed-local').innerHTML = `
        <div>Node ID: <strong>${status.node_id}</strong></div>
        <div style="font-size:12px; color:var(--text-dim); margin-top:4px;">
          Multicast: ${status.multicast_group}:${status.multicast_port} &bull;
          Peers: ${status.peer_count}
        </div>
      `;

      // Load peers
      const peers = await api('/federation/peers');
      const el = document.getElementById('fed-peers');
      el.innerHTML = '';
      if (!peers.length) {
        el.innerHTML = '<p class="placeholder">No peers discovered — enable federation in config.yml</p>';
        return;
      }
      peers.forEach(p => {
        const item = document.createElement('div');
        item.className = 'list-item';
        item.innerHTML = `
          <span><strong>${p.node_id}</strong> — ${p.host}:${p.port}</span>
          <span style="font-size:11px;">
            ${p.alive ? '<span style="color:var(--green)">●</span> alive' : '<span style="color:var(--red)">●</span> stale'}
            &bull; v${p.version} &bull; ${p.device_count} SDR(s)
          </span>
        `;
        el.appendChild(item);
      });
    } catch (e) {
      console.error('Federation status error:', e);
    }
  }

  // ── Init ────────────────────────────────────────────────
  async function init() {
    await loadDevices();
    await loadGPS();
    await loadEventHistory();
    await loadBaselines();
    await loadReports();
    await loadClassifierRules();
    await loadTXStatus();
    await loadFissureStatus();
    await loadFederationStatus();

    // WebSocket connections
    wsAlerts = connectWS('/ws/alerts', (msg) => {
      if (msg.type === 'alert') addAlertItem(msg.data);
    });

    wsStatus = connectWS('/ws/status', (msg) => {
      if (msg.type === 'device_status') loadDevices();
    });

    // Periodic refreshes
    setInterval(loadGPS, 5000);
    setInterval(loadTXStatus, 10000);
    setInterval(loadFederationStatus, 15000);
  }

  // PWA install prompt
  let deferredPrompt = null;
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPrompt = e;
  });

  // Service worker
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  }

  init();
})();
