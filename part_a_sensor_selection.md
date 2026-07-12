# Part A — Machine Study & Sensor Selection

## Machine: Industrial Air Compressor (Retrofit)

The plant environment is hot, dusty, and vibrating. The compressor already exists — we are retrofitting smart monitoring capabilities.

| Parameter | Sensor Chosen | Why (accuracy / cost / environment) | How It Mounts (Retrofit) | How You'd Calibrate / Validate |
|:---|:---|:---|:---|:---|
| **Discharge Pressure** | WIKA A-10 Pressure Transmitter (0–10 bar, 4–20 mA, ±0.5% FS, IP65) | 4–20 mA is noise-immune for long cable runs in a dusty plant; ±0.5% accuracy sufficient for leak detection; IP65 handles dust; <$100 unit cost | Threaded into existing ¼" NPT discharge port using a T-fitting — no drilling or welding | Calibrate against a dead-weight tester at 0, 3.5, 7, 10 bar points; validate by cross-checking with plant's existing analog gauge |
| **Motor Bearing Vibration** | PCB Piezotronics 356A15 IEPE Accelerometer + IFM VSE002 RMS Converter (10–1000 Hz, ±5%, IP67) | IEPE is industry standard for rotating machinery; RMS converter outputs 4–20 mA so no FFT processing needed at edge; magnetic base allows retrofit without machining; ISO 10816-3 compliant for medium machines | Magnetic base mount on motor DE (drive-end) bearing housing; cable routed through existing conduit with cable ties | Validate with a portable vibration analyzer (Fluke 810) side-by-side; calibrate RMS converter zero/span with shaker table |
| **Motor Winding Temperature** | RTD Pt100 (3-wire, Class B ±0.3°C) + IFM TA2531 Transmitter (4–20 mA) | Pt100 is stable and accurate for 0–150°C motor range; 3-wire compensates lead resistance; 4–20 mA loop robust in EMI environment; <$50 for RTD + transmitter | Thermal-paste the Pt100 bead into existing motor terminal-box thermowell (most motors have a spare M12 port); cable-tie the transmitter to the motor frame | Validate with infrared thermometer on motor casing; calibrate transmitter at 0°C (ice bath) and 100°C (boiling water) |
| **Air Flow / Load** | SUTO S401 Thermal Mass Flow Meter (insertion type, ±3% RD, IP65) | Thermal mass is independent of pressure/temp; insertion probe means no pipe cut — hot-tap retrofit; 4–20 mA output; detects unloaded running (leak/valve fault) | Drill ½" NPT hot-tap on discharge pipe >10D downstream of compressor; insert probe with isolation valve; seal with PTFE tape | Calibrate with a reference rotameter at 3 flow points; validate by correlating with compressor load current |
| **Oil Temperature** | Omega K-Type Thermocouple (1.5 mm sheath, ±1.1°C) + WIKA T32 Transmitter (4–20 mA) | K-type handles up to 400°C (compressor oil <120°C); mineral-insulated sheath resists vibration and oil splash; low cost; 4–20 mA loop | Thread ¼" NPT compression fitting into existing oil-sump drain plug (replace plug with thermowell adapter) | Validate with contact thermometer in sump; calibrate transmitter at ambient and 100°C reference block |

## Calibration & Validation Strategy

1. **Baseline Recording**: Run compressor at normal load for 30 minutes; record all 5 sensors to establish baseline signatures.
2. **Cross-Validation**: Use portable instruments (vibration analyzer, IR thermometer, dead-weight tester) to spot-check 10% of readings.
3. **Trend Validation**: Compare sensor trends against each other — pressure drop should correlate with flow increase; vibration rise should correlate with temperature rise.
4. **Alarm Thresholds**: Set based on ISO 10816-3 (vibration) and manufacturer oil specs (temperature); validate by inducing known faults (e.g., partially open blow-off valve).
