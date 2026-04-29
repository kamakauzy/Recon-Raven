/**
 * Map module — Leaflet.js GPS position + event markers.
 */
(function() {
  'use strict';

  const mapContainer = document.getElementById('leaflet-map');
  if (!mapContainer) return;

  // Load Leaflet CSS + JS dynamically
  const leafletCSS = document.createElement('link');
  leafletCSS.rel = 'stylesheet';
  leafletCSS.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
  document.head.appendChild(leafletCSS);

  const leafletJS = document.createElement('script');
  leafletJS.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
  leafletJS.onload = initMap;
  document.head.appendChild(leafletJS);

  let map = null;
  let positionMarker = null;
  let eventMarkers = [];

  function initMap() {
    map = L.map('leaflet-map').setView([0, 0], 2);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; OSM',
      maxZoom: 19,
    }).addTo(map);

    // Position marker
    positionMarker = L.circleMarker([0, 0], {
      radius: 8,
      color: '#00ff88',
      fillColor: '#00ff88',
      fillOpacity: 0.8,
    }).addTo(map);
    positionMarker.bindPopup('GPS Position');

    // Start polling GPS
    updatePosition();
    setInterval(updatePosition, 5000);

    // Load event markers
    loadEventMarkers();
  }

  async function updatePosition() {
    try {
      const res = await fetch('/api/gps/current');
      const gps = await res.json();

      if (gps.has_fix && gps.latitude && gps.longitude) {
        const latlng = [gps.latitude, gps.longitude];
        positionMarker.setLatLng(latlng);
        positionMarker.setPopupContent(
          `<strong>GPS Position</strong><br>` +
          `${gps.latitude.toFixed(6)}, ${gps.longitude.toFixed(6)}<br>` +
          `Alt: ${gps.altitude_m ? gps.altitude_m.toFixed(1) + 'm' : 'N/A'}<br>` +
          `Sats: ${gps.satellites || 'N/A'}`
        );

        if (map.getZoom() <= 2) {
          map.setView(latlng, 15);
        }
      }
    } catch (e) {
      // GPS unavailable
    }
  }

  async function loadEventMarkers() {
    try {
      const res = await fetch('/api/events?limit=200');
      const events = await res.json();

      // Clear old markers
      eventMarkers.forEach(m => map.removeLayer(m));
      eventMarkers = [];

      events.forEach(evt => {
        if (!evt.latitude || !evt.longitude) return;

        const color = evt.event_type === 'burst' ? '#ff4444' :
                      evt.event_type === 'alert' ? '#ffaa00' : '#4488ff';

        const marker = L.circleMarker([evt.latitude, evt.longitude], {
          radius: 5,
          color: color,
          fillColor: color,
          fillOpacity: 0.6,
        }).addTo(map);

        marker.bindPopup(
          `<strong>${evt.event_type}</strong><br>` +
          `Freq: ${evt.freq_mhz || '?'} MHz<br>` +
          `Power: ${evt.peak_power_db || '?'} dB<br>` +
          `${evt.timestamp}`
        );

        eventMarkers.push(marker);
      });
    } catch (e) {
      // Events unavailable
    }
  }

  // Expose for refresh
  window.RavenMap = { loadEventMarkers };
})();
