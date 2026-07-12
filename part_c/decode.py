#!/usr/bin/env python3
"""decode.py -- Part C: Decode, clean and validate compressor vibration + temperature register dump.

Usage:  python decode.py [--input assignment_raw_data.csv] [--outdir .]

Produces: cleaned_data.csv, plot.png

DECODING FIX: The vendor claims reg_40001=high word, reg_40002=low word.
That gives impossible values (~1e-20 mm/s). The actual wiring has the
words swapped: reg_40002=high, reg_40001=low. This yields ~2.37 mm/s
for the first row -- a realistic healthy compressor vibration.
Temperature (reg_40003, int16*0.1) decodes cleanly as documented.
"""

import argparse
import struct
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ISO 10816-3 Zone boundaries for Group 2 (Medium machine, 15-300 kW)
ISO_ZONES = {
    "rigid":    {"A/B": 1.4, "B/C": 2.8, "C/D": 4.5},
    "flexible": {"A/B": 2.3, "B/C": 4.5, "C/D": 7.1},
}

# Cleaning thresholds
VIB_PHYSICAL_MAX = 50.0
VIB_PHYSICAL_MIN = 0.0
TEMP_PHYSICAL_MIN = -10.0
TEMP_PHYSICAL_MAX = 150.0
STUCK_MIN_RUN_SECONDS = 30
EVENT_BASELINE_END = "2026-06-30 09:40:00"
EVENT_SIGMA = 3
EVENT_MIN_START = "2026-06-30 09:44:00"


def decode_vibration(reg_40001_hex, reg_40002_hex):
    """Decode vibration (mm/s) with CORRECTED word order: 40002=high, 40001=low."""
    if not reg_40001_hex or not reg_40002_hex:
        return None
    try:
        hi = bytes.fromhex(reg_40002_hex.strip())
        lo = bytes.fromhex(reg_40001_hex.strip())
        if len(hi) != 2 or len(lo) != 2:
            return None
        val = struct.unpack(">f", hi + lo)[0]
        if not np.isfinite(val):
            return None
        return val
    except (ValueError, struct.error):
        return None


def decode_temperature(reg_40003_hex):
    """Decode temperature (deg C) from int16 big-endian register, x0.1 C."""
    if not reg_40003_hex:
        return None
    try:
        raw = int(reg_40003_hex.strip(), 16)
    except ValueError:
        return None
    if raw > 32767:
        raw -= 65536
    return raw * 0.1


def find_stuck_runs(series, min_run):
    """Boolean mask for runs of identical non-null values >= min_run long."""
    mask = np.zeros(len(series), dtype=bool)
    n = len(series)
    i = 0
    while i < n:
        j = i + 1
        while j < n and pd.notna(series.iloc[i]) and series.iloc[j] == series.iloc[i]:
            j += 1
        if j - i >= min_run and pd.notna(series.iloc[i]):
            mask[i:j] = True
        i = j
    return mask


def get_zone(val, support="flexible"):
    z = ISO_ZONES[support]
    if val <= z["A/B"]:   return "A (new, acceptable)"
    elif val <= z["B/C"]: return "B (unrestricted long-term)"
    elif val <= z["C/D"]: return "C (unsatisfactory, short-term only)"
    else:                 return "D (unacceptable, shutdown)"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", default="assignment_raw_data.csv")
    ap.add_argument("--outdir", default=".")
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    # Read, sort, deduplicate
    raw = pd.read_csv(args.input, dtype=str, keep_default_na=False)
    raw["ts"] = pd.to_datetime(raw["timestamp"], errors="coerce")
    raw = raw.sort_values("ts", kind="stable").reset_index(drop=True)
    dup_mask = raw.duplicated(subset="ts", keep="first")
    n_duplicates_dropped = int(dup_mask.sum())
    raw = raw[~dup_mask].reset_index(drop=True)

    # Decode
    raw["vib_raw"] = raw.apply(
        lambda r: decode_vibration(r["reg_40001_hex"], r["reg_40002_hex"]), axis=1
    )
    raw["temp_raw"] = raw.apply(lambda r: decode_temperature(r["reg_40003_hex"]), axis=1)

    # Reindex to full 1-second timeline
    full_index = pd.date_range(raw["ts"].min(), raw["ts"].max(), freq="1s")
    df = raw.set_index("ts").reindex(full_index).reset_index()
    df.rename(columns={"index": "ts"}, inplace=True)

    # Anomaly masks
    is_dropout = df["timestamp"].isna()
    n_dropout = int(is_dropout.sum())

    is_malformed_vib = (~is_dropout) & df["vib_raw"].isna()
    is_malformed_temp = (~is_dropout) & df["temp_raw"].isna()

    is_spike_vib = df["vib_raw"].notna() & (
        (df["vib_raw"].abs() > VIB_PHYSICAL_MAX) | (df["vib_raw"] < VIB_PHYSICAL_MIN)
    )
    is_spike_temp = df["temp_raw"].notna() & (
        (df["temp_raw"] < TEMP_PHYSICAL_MIN) | (df["temp_raw"] > TEMP_PHYSICAL_MAX)
    )

    stuck_mask = find_stuck_runs(df["temp_raw"], STUCK_MIN_RUN_SECONDS)
    is_stuck_temp = stuck_mask & (~is_dropout) & (~is_spike_temp)

    # Event detection via baseline statistics
    vib_ok_for_baseline = (
        df["vib_raw"].notna() & (~is_spike_vib) & (df["ts"] < EVENT_BASELINE_END)
    )
    baseline_mean = df.loc[vib_ok_for_baseline, "vib_raw"].mean()
    baseline_std = df.loc[vib_ok_for_baseline, "vib_raw"].std()
    event_threshold = baseline_mean + EVENT_SIGMA * baseline_std

    is_event = (
        (df["ts"] >= EVENT_MIN_START)
        & (~is_dropout)
        & (~is_spike_vib)
        & df["vib_raw"].notna()
        & (df["vib_raw"] > event_threshold)
    )

    # Assemble output columns & status (most severe first)
    vib_out = df["vib_raw"].copy()
    temp_out = df["temp_raw"].copy()
    status = pd.Series("ok", index=df.index, dtype=object)

    status[is_dropout] = "dropout"
    status[(~is_dropout) & is_stuck_temp] = "stuck"
    temp_out[is_stuck_temp] = np.nan

    status[(~is_dropout) & (is_malformed_vib | is_malformed_temp) & (status == "ok")] = "malformed"
    vib_out[is_malformed_vib] = np.nan
    temp_out[is_malformed_temp] = np.nan

    status[(~is_dropout) & (is_spike_vib | is_spike_temp) & (status == "ok")] = "spike"
    vib_out[is_spike_vib] = np.nan
    temp_out[is_spike_temp] = np.nan

    status[(~is_dropout) & is_event & (status == "ok")] = "event"

    # Write CSV
    out = pd.DataFrame({
        "timestamp": full_index.strftime("%Y-%m-%d %H:%M:%S"),
        "vibration_mm_s": vib_out.round(3),
        "temperature_c": temp_out.round(2),
        "status": status,
    })
    out.to_csv(outdir / "cleaned_data.csv", index=False)

    # Console summary
    print("=" * 70)
    print("PART C — DECODING & CLEANING SUMMARY")
    print("=" * 70)
    print("\n[DECODING FIX]")
    print("  Vendor claimed: 40001=high, 40002=low (big-endian float32)")
    print("  Actual data:    40002=high, 40001=low (word order swapped)")
    print("  Proof: Row 0 vendor order -> 8ACB 4017 -> 1.08e-20 mm/s (impossible)")
    print("         Row 0 swapped order  -> 4017 8ACB -> 2.3678 mm/s (reasonable)")

    print(f"\n[DATA QUALITY]")
    print(f"  Total seconds in hour      : {len(full_index)}")
    print(f"  Duplicate rows dropped     : {n_duplicates_dropped}")
    print(f"  Dropout samples            : {n_dropout}")
    print(f"  Stuck temperature samples  : {int(is_stuck_temp.sum())}")
    print(f"  Spike samples              : {int((is_spike_vib | is_spike_temp).sum())}")
    print(f"  Malformed samples          : {int((is_malformed_vib | is_malformed_temp).sum())}")
    print(f"  Event samples (kept)       : {int(is_event.sum())}")
    print(f"  OK samples                 : {int((status == 'ok').sum())}")

    dropout_rows = df[is_dropout]
    if len(dropout_rows):
        print(f"\n[DATA DROPOUT] {dropout_rows['ts'].min()} -> {dropout_rows['ts'].max()}")
        print(f"  Missing samples: {len(dropout_rows)}")

    stuck_rows = df[is_stuck_temp]
    if len(stuck_rows):
        print(f"\n[STUCK TEMPERATURE] {stuck_rows['ts'].min()} -> {stuck_rows['ts'].max()}")
        print(f"  Frozen at {df.loc[is_stuck_temp, 'temp_raw'].iloc[0]:.1f} C ({len(stuck_rows)} samples)")

    peak_idx = df["temp_raw"][~is_spike_temp].idxmax()
    print(f"\n[PEAK TEMPERATURE] {df.loc[peak_idx, 'temp_raw']:.1f} degC at {df.loc[peak_idx, 'ts']}")

    vib_clean = df["vib_raw"][~is_spike_vib & ~is_malformed_vib & ~is_dropout]
    ts_clean = df["ts"][~is_spike_vib & ~is_malformed_vib & ~is_dropout]
    start_vib = vib_clean.iloc[0]
    end_vib = vib_clean.iloc[-1]
    print(f"\n[VIBRATION START] {start_vib:.4f} mm/s")
    print(f"[VIBRATION END]   {end_vib:.4f} mm/s")

    first_60 = vib_clean[ts_clean < ts_clean.iloc[0] + pd.Timedelta(seconds=60)]
    last_60 = vib_clean[ts_clean > ts_clean.iloc[-1] - pd.Timedelta(seconds=60)]
    rms_first = np.sqrt((first_60 ** 2).mean())
    rms_last = np.sqrt((last_60 ** 2).mean())
    print(f"\n[VIBRATION RMS] first 60s: {rms_first:.2f} mm/s")
    print(f"[VIBRATION RMS] last 60s : {rms_last:.2f} mm/s")
    print(f"  (baseline mean={baseline_mean:.2f}, std={baseline_std:.2f}, "
          f"3-sigma threshold={event_threshold:.2f} mm/s)")

    print(f"\n[ISO 10816-3 ZONES] Medium machine, Group 2")
    print(f"  Rigid:    A/B={ISO_ZONES['rigid']['A/B']}, B/C={ISO_ZONES['rigid']['B/C']}, C/D={ISO_ZONES['rigid']['C/D']} mm/s")
    print(f"  Flexible: A/B={ISO_ZONES['flexible']['A/B']}, B/C={ISO_ZONES['flexible']['B/C']}, C/D={ISO_ZONES['flexible']['C/D']} mm/s")
    print(f"  Start ({start_vib:.4f} mm/s): Zone {get_zone(start_vib, 'rigid')} (rigid) / {get_zone(start_vib, 'flexible')} (flexible)")
    print(f"  End   ({end_vib:.4f} mm/s): Zone {get_zone(end_vib, 'rigid')} (rigid) / {get_zone(end_vib, 'flexible')} (flexible)")

    print(f"\n[REAL MACHINE EVENT — KEPT]")
    print(f"  Type:  Bearing degradation / developing fault")
    print(f"  Start: ~{EVENT_MIN_START}")
    print(f"  Story: Vibration climbs from ~{start_vib:.1f} to ~{end_vib:.1f} mm/s while temperature rises")
    print(f"         from ~46C to ~63C — both sensors agree on mechanical degradation.")
    print(f"  Event samples labeled: {int(is_event.sum())}")
    print(f"\nClean data written to: {outdir / 'cleaned_data.csv'}")

    # =====================================================================
    # Plot
    # =====================================================================
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 9), sharex=True)

    event_pts = out["status"] == "event"

    # --- Dropout band (system-wide, both subplots) -----------------------
    dropout_span = None
    if len(dropout_rows):
        dropout_span = (dropout_rows["ts"].min(), dropout_rows["ts"].max())
        ax1.axvspan(dropout_span[0], dropout_span[1], color="gray", alpha=0.2, label="dropout")
        ax2.axvspan(dropout_span[0], dropout_span[1], color="gray", alpha=0.2, label="dropout")

    # --- Vibration plot --------------------------------------------------
    ax1.plot(full_index, vib_out, color="#2563eb", linewidth=0.8, label="vibration (kept)")
    ax1.scatter(full_index[event_pts], vib_out[event_pts], color="#dc2626", s=5,
                label="event (genuine rise)", zorder=5)

    # ISO zone lines (no individual labels — consolidated in text box below)
    for support, color, style in [("rigid", "green", "--"), ("flexible", "purple", ":")]:
        z = ISO_ZONES[support]
        ax1.axhline(y=z["A/B"], color=color, linestyle=style, alpha=0.5)
        ax1.axhline(y=z["B/C"], color=color, linestyle=style, alpha=0.7)
        ax1.axhline(y=z["C/D"], color=color, linestyle=style, alpha=0.9)

    ax1.set_ylabel("Vibration (mm/s RMS)", fontsize=12)
    ax1.set_title("Compressor Vibration & Temperature Over 1 Hour", fontsize=14, fontweight="bold")
    ax1.legend(loc="upper left", fontsize=8)
    ax1.grid(True, alpha=0.3)
    ax1.set_ylim(0, 12)

    # ISO zone threshold annotation (clean, single text box)
    iso_text = ("Thresholds — Green dashed = Rigid (A/B, B/C, C/D)\n"
                "               Purple dotted = Flexible (A/B, B/C, C/D)")
    ax1.text(0.98, 0.02, iso_text, transform=ax1.transAxes,
             fontsize=8, verticalalignment="bottom", horizontalalignment="right",
             bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="gray", alpha=0.85))

    # Event annotation
    ax1.annotate("Bearing degradation event\n(vibration + temp rise)",
                 xy=(pd.Timestamp("2026-06-30 09:52:00"), 8),
                 fontsize=10, color="darkorange", fontweight="bold",
                 arrowprops=dict(arrowstyle="->", color="darkorange"))

    # --- Temperature plot ------------------------------------------------
    ax2.plot(full_index, temp_out, color="#ea580c", linewidth=0.8, label="temperature (kept)")
    ax2.scatter(full_index[event_pts], temp_out[event_pts], color="#dc2626", s=5,
                label="event (genuine rise)", zorder=5)

    ax2.set_ylabel("Temperature (deg C)", fontsize=12)
    ax2.set_xlabel("Time (UTC)", fontsize=12)
    ax2.legend(loc="upper left", fontsize=8)
    ax2.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(outdir / "plot.png", dpi=150)
    print(f"Plot saved to: {outdir / 'plot.png'}")


if __name__ == "__main__":
    sys.exit(main())