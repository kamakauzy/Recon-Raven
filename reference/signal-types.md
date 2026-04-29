# Signal Types & Indicators

Quick identification guide for common signal types encountered during field SIGINT operations.

---

## Signal Reference Table

| Signal Type | Modulation | Waterfall Indicators | Common Sources |
|-------------|-----------|---------------------|----------------|
| **Voice** | FM / AM | Smooth continuous carrier with audio | FRS/GMRS, Baofeng, amateur radio |
| **Data Burst** | FSK / LoRa | Short pulsing bursts, repeating | Sensor nets, trackers, telemetry |
| **Digital Voice** | DMR / TETRA / P25 | Compressed bursts, irregular timing | May hop channels, short packets |
| **WiFi** | OFDM | Dense, constant wideband activity | Routers, access points, IoT |
| **Beacon** | Any | Repeating at fixed interval | Meshtastic, LoRa nodes, GPS trackers |
| **Weather** | FSK / AFSK | Periodic data bursts, predictable | Weather stations, NOAA, ISM sensors |
| **Broadcast** | FM (wideband) | Wide constant carrier | Commercial FM radio stations |

## Field Tips

- **Strong ≠ threat** — log behavior before assuming intent
- Friendly signals may overlap adversary bands
- **Repetition = predictability = exploitable**
- A single reading is never enough — propagation changes with terrain, time, and weather
- Prioritize signals by: repetition rate, correlation to movement, proximity, and pattern breaks

## Four Tactical Bands to Monitor

| Band | Frequency | Typical Activity |
|------|-----------|-----------------|
| VHF | ~146 MHz | Voice communications |
| UHF | ~462 MHz | FRS/GMRS voice |
| ISM Low | 433.92 MHz | Data sensors, weather stations |
| ISM High | 915 MHz | LoRa, Meshtastic, IoT data |
