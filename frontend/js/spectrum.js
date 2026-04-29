/**
 * Spectrum Waterfall — renders live power sweep data on a canvas.
 * Connects to /ws/spectrum for real-time frames.
 */
(function() {
  'use strict';

  const canvas = document.getElementById('waterfall');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');

  // Configuration
  const MIN_DB = -60;
  const MAX_DB = -10;
  const SCROLL_SPEED = 2;  // pixels per frame

  let freqStart = 400;
  let freqEnd = 450;
  let ws = null;

  // Set canvas pixel buffer to match displayed size.
  // Some embedded browsers (VS Code Simple Browser) report clientWidth=0.
  // In that case, keep the HTML-attribute default (1200x400) and let CSS scale display.
  function resizeCanvas() {
    const rect = canvas.getBoundingClientRect();
    const w = rect.width || canvas.offsetWidth;
    const h = rect.height || canvas.offsetHeight;
    if (w > 50 && h > 50) {
      canvas.width = Math.round(w);
      canvas.height = Math.round(h);
    }
    // else: keep existing canvas.width/height (1200x400 from HTML attr)
  }
  window.addEventListener('resize', resizeCanvas);
  resizeCanvas();

  // Color map — viridis-like gradient
  const colormap = buildColormap();

  function buildColormap() {
    const c = document.createElement('canvas');
    c.width = 256; c.height = 1;
    const g = c.getContext('2d');
    const grad = g.createLinearGradient(0, 0, 256, 0);
    grad.addColorStop(0.0, '#000020');
    grad.addColorStop(0.15, '#0d0887');
    grad.addColorStop(0.3, '#6a00a8');
    grad.addColorStop(0.45, '#b12a90');
    grad.addColorStop(0.6, '#e16462');
    grad.addColorStop(0.75, '#fca636');
    grad.addColorStop(0.9, '#f0f921');
    grad.addColorStop(1.0, '#ffffff');
    g.fillStyle = grad;
    g.fillRect(0, 0, 256, 1);
    return g.getImageData(0, 0, 256, 1).data;
  }

  function dbToColor(db) {
    const norm = Math.max(0, Math.min(1, (db - MIN_DB) / (MAX_DB - MIN_DB)));
    const idx = Math.floor(norm * 255) * 4;
    return [colormap[idx], colormap[idx+1], colormap[idx+2]];
  }

  // Draw a single spectrum line (scroll waterfall down)
  function drawSpectrumLine(powers) {
    if (!powers || powers.length === 0) return;

    // Scroll existing image down
    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    ctx.putImageData(imageData, 0, SCROLL_SPEED);

    // Draw new line at top
    const lineData = ctx.createImageData(canvas.width, SCROLL_SPEED);
    const binWidth = canvas.width / powers.length;

    for (let i = 0; i < powers.length; i++) {
      const [r, g, b] = dbToColor(powers[i]);
      const x0 = Math.floor(i * binWidth);
      const x1 = Math.floor((i + 1) * binWidth);

      for (let row = 0; row < SCROLL_SPEED; row++) {
        for (let x = x0; x < x1 && x < canvas.width; x++) {
          const idx = (row * canvas.width + x) * 4;
          lineData.data[idx] = r;
          lineData.data[idx + 1] = g;
          lineData.data[idx + 2] = b;
          lineData.data[idx + 3] = 255;
        }
      }
    }

    ctx.putImageData(lineData, 0, 0);

    // Draw frequency axis labels
    drawFreqAxis(powers.length);

    // Update peak indicator
    const peak = Math.max(...powers);
    const peakFreq = freqStart + (powers.indexOf(peak) / powers.length) * (freqEnd - freqStart);
    const peakEl = document.getElementById('spectrum-peak');
    if (peakEl) {
      peakEl.textContent = `Peak: ${peak.toFixed(1)} dB @ ${peakFreq.toFixed(2)} MHz`;
    }
  }

  function drawFreqAxis(binCount) {
    const h = canvas.height;
    ctx.fillStyle = 'rgba(0,0,0,0.6)';
    ctx.fillRect(0, h - 20, canvas.width, 20);

    ctx.fillStyle = '#aaa';
    ctx.font = '10px monospace';
    ctx.textAlign = 'center';

    const numLabels = Math.min(10, Math.floor(canvas.width / 60));
    for (let i = 0; i <= numLabels; i++) {
      const x = (i / numLabels) * canvas.width;
      const freq = freqStart + (i / numLabels) * (freqEnd - freqStart);
      ctx.fillText(freq.toFixed(1), x, h - 5);
    }
  }

  // Draw power scale legend
  function drawColorbar() {
    const barWidth = 15;
    const barX = canvas.width - barWidth - 5;

    for (let y = 0; y < canvas.height - 20; y++) {
      const db = MAX_DB - (y / (canvas.height - 20)) * (MAX_DB - MIN_DB);
      const [r, g, b] = dbToColor(db);
      ctx.fillStyle = `rgb(${r},${g},${b})`;
      ctx.fillRect(barX, y, barWidth, 1);
    }

    ctx.fillStyle = '#aaa';
    ctx.font = '9px monospace';
    ctx.textAlign = 'right';
    ctx.fillText(`${MAX_DB}dB`, barX - 2, 10);
    ctx.fillText(`${MIN_DB}dB`, barX - 2, canvas.height - 25);
  }

  // Handle incoming spectrum frame
  function handleSpectrumFrame(msg) {
    if (msg.type === 'spectrum' || msg.event_type === 'spectrum') {
      const data = msg.data || msg;
      if (data.freq_start_mhz) freqStart = data.freq_start_mhz;
      if (data.freq_end_mhz) freqEnd = data.freq_end_mhz;
      drawSpectrumLine(data.powers);
      drawColorbar();
    }
  }

  // Connect WebSocket
  function connectSpectrumWS() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(proto + '//' + location.host + '/ws/spectrum');

    ws.onmessage = (e) => {
      try {
        handleSpectrumFrame(JSON.parse(e.data));
      } catch(err) {
        console.error('Spectrum WS parse error:', err);
      }
    };

    ws.onclose = () => {
      setTimeout(connectSpectrumWS, 3000);
    };
    ws.onerror = () => ws.close();
  }

  // Initial blank canvas
  ctx.fillStyle = '#000020';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = '#555';
  ctx.font = '14px monospace';
  ctx.textAlign = 'center';
  ctx.fillText('Start a power sweep to see live spectrum', canvas.width / 2, canvas.height / 2);

  connectSpectrumWS();

  // Expose for external use
  window.RavenSpectrum = {
    drawSpectrumLine,
    setFreqRange: (lo, hi) => { freqStart = lo; freqEnd = hi; },
  };
})();
