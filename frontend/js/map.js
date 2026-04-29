/**
 * Map module — Leaflet.js GPS position + event markers.
 * Deferred initialization: map is only created when the Map tab is first shown.
 */
(function() {
  'use strict';

  let map = null;
  let positionMarker = null;
  let eventMarkers = [];
  let gpsInterval = null;

  function initMap() {
    if (map) return; // already initialized
    if (typeof L === 'undefined') return;

    const el = document.getElementById('leaflet-map');
    if (!el) return;

    map = L.map('leaflet-map', { zoomControl: true }).setView([34.79, -86.50], 13);

    L.tileLayer('/tiles/{z}/{x}/{y}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a>',
      maxZoom: 19,
    }).addTo(map);

    // GPS position marker
    positionMarker = L.circleMarker([0, 0], {
      radius: 8,
      color: '#00ff88',
      fillColor: '#00ff88',
      fillOpacity: 0.8,
    }).addTo(map);
    positionMarker.bindPopup('GPS Position');

    // Start polling GPS
    updatePosition();
    gpsInterval = setInterval(updatePosition, 5000);

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
          '<strong>GPS Position</strong><br>' +
          gps.latitude.toFixed(6) + ', ' + gps.longitude.toFixed(6) + '<br>' +
          'Alt: ' + (gps.altitude_m ? gps.altitude_m.toFixed(1) + 'm' : 'N/A') + '<br>' +
          'Sats: ' + (gps.satellites || 'N/A')
        );

        // Auto-center only on first GPS fix
        if (map.getZoom() <= 13) {
          map.setView(latlng, 15);
        }
      }
    } catch (e) { /* GPS unavailable */ }
  }

  async function loadEventMarkers() {
    if (!map) return;
    try {
      const res = await fetch('/api/events?limit=200');
      const events = await res.json();

      eventMarkers.forEach(function(m) { map.removeLayer(m); });
      eventMarkers = [];

      events.forEach(function(evt) {
        if (!evt.latitude || !evt.longitude) return;

        var color = evt.event_type === 'burst' ? '#ff4444' :
                    evt.event_type === 'alert' ? '#ffaa00' : '#4488ff';

        var marker = L.circleMarker([evt.latitude, evt.longitude], {
          radius: 5, color: color, fillColor: color, fillOpacity: 0.6,
        }).addTo(map);

        marker.bindPopup(
          '<strong>' + evt.event_type + '</strong><br>' +
          'Freq: ' + (evt.freq_mhz || '?') + ' MHz<br>' +
          'Power: ' + (evt.peak_power_db || '?') + ' dB<br>' +
          evt.timestamp
        );
        eventMarkers.push(marker);
      });
    } catch (e) { /* Events unavailable */ }
  }

  window.RavenMap = {
    init: function() {
      initMap();
      // Double invalidateSize with delay to ensure tiles fill container
      if (map) {
        map.invalidateSize();
        setTimeout(function() { map.invalidateSize(); }, 300);
        setTimeout(function() { map.invalidateSize(); }, 600);
      }
    },
    invalidateSize: function() {
      if (map) map.invalidateSize();
    },
    loadEventMarkers: loadEventMarkers
  };
})();
