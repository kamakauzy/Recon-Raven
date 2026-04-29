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

  // ── Init ────────────────────────────────────────────────
  async function init() {
    await loadDevices();
    await loadGPS();
    await loadEventHistory();
    await loadBaselines();
    await loadReports();

    // WebSocket connections
    wsAlerts = connectWS('/ws/alerts', (msg) => {
      if (msg.type === 'alert') addAlertItem(msg.data);
    });

    wsStatus = connectWS('/ws/status', (msg) => {
      if (msg.type === 'device_status') loadDevices();
    });

    // Periodic GPS refresh
    setInterval(loadGPS, 5000);
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
