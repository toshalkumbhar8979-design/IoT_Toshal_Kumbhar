# IoT Assignment — Embedded IoT Intern

**Candidate:** [Your Full Name]  
**Date:** July 2026  
**Assignment:** Take-Home Embedded IoT Intern Assignment — Sparkline

---

## Table of Contents

1. [Setup & Usage](#setup--usage)
2. [Part A — Sensor Selection](#part-a--sensor-selection)
3. [Part B — Gateway](#part-b--gateway)
4. [Part C — Data Decoding & Validation](#part-c--data-decoding--validation)
5. [Judgment Call](#judgment-call)
6. [Assumptions, Limitations & Tools](#assumptions-limitations--tools)

---

## Setup & Usage

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Run Part B — Gateway

```bash
cd part_b
# Using config file (recommended)
python gateway.py --config gateway.ini

# Or override with CLI arguments
python gateway.py --broker test.mosquitto.org --topic sparkline/firstname-lastname/compressor1 --device-id firstname-lastname-compressor-1
```

**Signal simulated:** Discharge pressure hovering around 7 bar with Gaussian noise (σ = 0.05 bar) and slow process drift.  
**Sample rate:** 1 Hz (1 message per second).  
**JSON schema:** `device_id`, `seq`, `timestamp`, `parameter`, `value`, `unit`.  
**Topic:** `sparkline/firstname-lastname/compressor1`

**Example message (single line, no line breaks):**
```json
{"device_id":"firstname-lastname-compressor-1","seq":1240,"timestamp":"2026-07-05T10:00:00Z","parameter":"discharge_pressure","value":7.03,"unit":"bar"}
```

**Store-and-forward demonstration:**
1. Start the gateway: `python gateway.py --config gateway.ini`
2. Block the broker for ~20 seconds: `sudo iptables -A OUTPUT -p tcp --dport 1883 -j DROP`
3. Observe "Buffered" messages in console — readings are stored in a `deque` with local timestamps
4. Restore connection: `sudo iptables -F`
5. Observe "Flushed" messages — all buffered readings publish in order with no gap in sequence numbers

### Run Part C — Decode & Validate

```bash
cd part_c
python decode.py
```

Outputs:
- `cleaned_data.csv` — one row per second with `timestamp`, `vibration_mm_s`, `temperature_c`, `status`
- `plot.png` — vibration + temperature chart with ISO 10816 zone lines

---

## Part A — Sensor Selection

See `part_a_sensor_selection.pdf` for the full table.

**Summary:** Five parameters selected for an industrial air compressor retrofit in a hot, dusty, vibrating plant:

| Parameter | Sensor | Key Reason |
|-----------|--------|------------|
| Discharge Pressure | WIKA A-10 (4-20mA, ±0.5%, IP65) | Noise-immune current loop; detects leaks/pressure drops |
| Motor Bearing Vibration | PCB 356A15 IEPE + IFM RMS Converter | ISO 10816 compliant; magnetic mount retrofit; RMS→4-20mA |
| Motor Winding Temperature | RTD Pt100 3-wire + IFM TA2531 | ±0.3°C accuracy; 3-wire compensates lead resistance |
| Air Flow / Load | SUTO S401 Thermal Mass (insertion) | Hot-tap retrofit; independent of pressure/temperature |
| Oil Temperature | Omega K-Type + WIKA T32 | Mineral-insulated sheath resists oil splash and vibration |

---

## Part B — Gateway

**File:** `part_b/gateway.py`

**Architecture:**
- `CompressorGateway` class encapsulates all behavior
- Settings read from `gateway.ini` or CLI arguments — no hard-coded values in the body
- `generate_pressure()` produces realistic signal with Gaussian noise
- `create_message()` stamps ISO-8601 UTC timestamp at **sample time**, not publish time
- `deque` buffer stores messages during outages; `flush_buffer()` sends them on reconnection
- `connect_with_backoff()` implements exponential backoff (1s, 2s, 4s, ... max 30s)
- Monotonically increasing `seq` proves no message loss

**Screenshot:** `part_b/mqtt_proof.png` — shows MQTT Explorer receiving live messages on topic `sparkline/firstname-lastname/compressor1`

---

## Part C — Data Decoding & Validation

**File:** `part_c/decode.py`

### Decoding Fix

The vendor's register map claims:
> reg_40001 = high word, reg_40002 = low word, IEEE-754 float32, big-endian

**This is incorrect.** Decoding row 0 with the vendor's word order gives **1.08×10⁻²⁰ mm/s** — physically impossible.

The **actual data requires swapped word order**: reg_40002 = high word, reg_40001 = low word.
With this correction, row 0 decodes to **2.3678 mm/s** — a realistic baseline for a running compressor.

This is a classic Modbus word-order bug: the sensor was likely configured for "swapped" word order while the datasheet documents "standard" big-endian.

### Specific Numbers

| Item | Value |
|------|-------|
| **Data dropout** | 2026-06-30 09:20:00 to 09:24:59 — **300 samples missing** |
| **Peak temperature** | **63.3°C** at 2026-06-30 09:59:56 |
| **Vibration at start** | **2.3678 mm/s** — Zone B (rigid) / Zone B (flexible) |
| **Vibration at end** | **9.8869 mm/s** — Zone D (rigid) / Zone D (flexible) |
| **Discarded: Dropout** | **300** |
| **Discarded: Stuck** | **239** (temperature frozen at 48.0°C from 09:10:00 to 09:13:59) |
| **Discarded: Spike** | **4** (vibration sentinel 9999.0; temperature sentinels 3275.0°C and -50.0°C) |
| **Discarded: Malformed** | **5** (blank hex registers) |
| **Total discarded** | **548** |

### Real Machine Event (KEPT)

**Type:** Bearing degradation / developing mechanical fault  
**Start:** ~2026-06-30 09:44:00  
**Physical story:** Vibration climbs steadily from ~2.8 mm/s to ~9.9 mm/s while temperature rises from ~46°C to ~63°C. Both sensors agree on the same physical mechanism — increased friction in a bearing generates heat (temperature rise) and mechanical oscillation (vibration rise). This is the classic signature of bearing degradation, not sensor noise.  
**Samples labeled `event`:** 755

---

## Judgment Call

I discovered the vendor's register map was wrong when the claimed big-endian word order produced physically impossible vibration values of ~10⁻²⁰ mm/s. I tested the alternative word order (40002 as high word, 40001 as low word) which produced ~2.37 mm/s — a realistic baseline for a running compressor. I kept the bearing degradation event starting at ~09:44:00 because both vibration and temperature rose together in a physically consistent way (vibration climbed from 2.8 to 9.9 mm/s while temperature rose from 46°C to 63°C), which is the signature of real bearing damage rather than sensor noise. I discarded the 48.0°C stuck readings at 09:10-09:14 because 240 identical consecutive values with zero variance is impossible for a real thermal process — a temperature sensor on a running compressor must show at least quantization noise. The 9999.0 vibration spikes were obvious sentinel values (hex `3C00 461C` decodes to exactly 9999.0), and the 3275°C temperature readings (hex `7FEE` = 32750 decimal) are clearly register overflow sentinels.

---

## Assumptions, Limitations & Tools

### Assumptions
1. The compressor is a medium-sized industrial rotary screw compressor (15–300 kW), placing it in ISO 10816 Group 2.
2. The missing 5-minute gap (09:20–09:25) is a communication dropout, not a machine shutdown — no data exists to distinguish.
3. The 9999.0 vibration value is a firmware sentinel for "sensor fault" rather than a real reading.
4. The machine foundation is rigid (concrete pad) for ISO 10816 zone classification, though flexible boundaries are also shown.

### Limitations
1. The gateway simulation does not include actual MQTT broker authentication — uses the public test.mosquitto.org broker.
2. No TLS/SSL is configured in the gateway for simplicity; production would require certificates.
3. The cleaned CSV leaves blank cells for discarded readings rather than interpolating — interpolation would be a valid alternative but introduces synthetic data.

### Tools & References Used
- Python 3.11, pandas, matplotlib, paho-mqtt
- ISO 10816-3:2009 — Mechanical vibration — Evaluation of machine vibration by measurements on non-rotating parts
- Modbus Application Protocol Specification V1.1b3 — for register addressing and data types
- IEEE 754-2008 — for float32 encoding verification

### Approach Rejected
I initially considered using a statistical outlier detection (Z-score > 3) to clean the data automatically. I rejected this because it would have flagged the real bearing degradation event as an outlier and deleted it — exactly the mistake the assignment warns against. Instead, I used domain-knowledge thresholds (vibration > 100 mm/s impossible, temperature > 200°C impossible) combined with physical correlation checks (both sensors must agree) to distinguish real faults from bad data.

---

## Folder Structure

```
IoT_<YourFullName>/
├── README.md                          <- This file
├── requirements.txt                   <- Python dependencies
├── part_a_sensor_selection.pdf        <- Part A sensor table
├── part_a_sensor_selection.md         <- Source markdown for PDF
├── part_b/
│   ├── gateway.py                     <- Gateway program
│   ├── gateway.ini                    <- Default config
│   └── mqtt_proof.png                 <- Screenshot of subscriber
└── part_c/
    ├── decode.py                      <- Decode & validation script
    ├── assignment_raw_data.csv        <- Input data (provided)
    ├── cleaned_data.csv               <- Output: cleaned dataset
    └── plot.png                       <- Output: validation plot
```
