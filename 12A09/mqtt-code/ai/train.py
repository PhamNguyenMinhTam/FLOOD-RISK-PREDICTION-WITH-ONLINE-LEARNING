#!/usr/bin/env python3
# ======================================================
# train_predict_realtime.py  (HYBRID ONLINE LEARNING - FINAL)
#
# DEMO (JSN-SR04T):
# - level: water height from bottom (cm), expected 0..15
# - danger level: 13 cm (risk_score -> 100 near/over danger)
#
# INPUT (append-only CSV):
#   12A09/mqtt-data/raw/telecsv.csv
#   columns: ts, level, level_rate
#
# OUTPUT (numeric-only, InfluxDB/Grafana friendly):
#   12A09/mqtt-data/processed/ai_data_out.csv
#   columns: ts, level, level_rate, ai_s, risk_score
#
# HYBRID OPTION A:
# - Bootstrap-train from embedded dataset (your provided table)
# - Predict realtime for new telemetry rows
# - Online learning:
#     pseudo-label y_phys = (danger - level)/rate (clamped)
#     partial_fit in small batches with guard-rails
#
# IMPORTANT FEATURE:
# - On start, it EXPORTS ALL EXISTING telecsv.csv rows immediately
#   so you WILL see ai_data_out.csv right away.
# ======================================================

import os
import time
import numpy as np
import pandas as pd
from io import StringIO
from joblib import dump, load

from sklearn.linear_model import SGDRegressor
from sklearn.preprocessing import StandardScaler

# =========================
# PATHS
# =========================
CODE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(CODE_DIR))
TELECSV_PATH = os.getenv(
    "TELECSV_PATH",
    os.path.join(PROJECT_ROOT, "mqtt-data", "raw", "telecsv.csv"),
)
OUT_PATH = os.getenv(
    "OUT_PATH",
    os.path.join(PROJECT_ROOT, "mqtt-data", "processed", "ai_data_out.csv"),
)
MODEL_PATH = os.getenv(
    "MODEL_PATH",
    os.path.join(CODE_DIR, "models", "flood_ai_online_cm.joblib"),
)

# =========================
# CSV COLUMNS
# =========================
COL_TS = "ts"
COL_LV = "level"
COL_LR = "level_rate"

# =========================
# CONFIG
# =========================
DANGER_LEVEL_CM = 13.0
LEVEL_MIN = 0.0
LEVEL_MAX = 15.0

AI_S_MAX = 6 * 3600.0          # clamp time-to-danger to 6 hours
MIN_RATE_FOR_LEARN = 0.01      # cm/s, below this: do not learn (too noisy)
BATCH_SIZE = 20                # online update batch size
FOLLOW_SLEEP = 0.25            # seconds

# =========================
# HELPERS
# =========================
def clamp(x: float, lo: float, hi: float) -> float:
    return float(max(lo, min(hi, x)))

def risk_score(ai_s: float) -> float:
    """
    Numeric-only 0..100.
    Use Grafana thresholds to colorize.
    """
    if ai_s <= 0:    return 100.0
    if ai_s <= 10:   return 95.0
    if ai_s <= 30:   return 85.0
    if ai_s <= 60:   return 75.0
    if ai_s <= 120:  return 60.0
    if ai_s <= 300:  return 45.0
    if ai_s <= 900:  return 30.0
    if ai_s <= 1800: return 20.0
    return 10.0

def physics_pseudo_label(level_cm: float, rate_cms: float) -> float:
    """
    Pseudo-label (teacher signal) for online learning.
    """
    if level_cm >= DANGER_LEVEL_CM:
        return 0.0
    if rate_cms <= 0:
        return AI_S_MAX
    return clamp((DANGER_LEVEL_CM - level_cm) / rate_cms, 0.0, AI_S_MAX)

def parse_csv_line(line: str):
    """
    Parse one CSV data row (no header).
    Expect: ts,level,level_rate,...
    Return (ts, level, rate) or None
    """
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 3:
        return None
    ts = parts[0]
    try:
        level = float(parts[1])
        rate  = float(parts[2])
    except Exception:
        return None
    return ts, level, rate

# =========================
# BOOTSTRAP DATASET (your provided data)
# =========================
BOOTSTRAP_CSV = """ts,level,level_rate,time_to_danger_s
0,0.5,0.02,625
1,2.0,0.02,550
2,4.0,0.02,450
3,6.0,0.02,350
4,8.0,0.02,250
5,10.0,0.02,150
6,11.5,0.02,75
7,12.5,0.02,25
8,0.5,0.05,250
9,2.0,0.05,220
10,4.0,0.05,180
11,6.0,0.05,140
12,8.0,0.05,100
13,10.0,0.05,60
14,11.5,0.05,30
15,12.5,0.05,10
16,0.5,0.10,125
17,2.0,0.10,110
18,4.0,0.10,90
19,6.0,0.10,70
20,8.0,0.10,50
21,10.0,0.10,30
22,11.5,0.10,15
23,12.5,0.10,5
24,9.0,0.15,26.6667
25,10.5,0.15,16.6667
26,11.5,0.15,10.0
27,12.0,0.15,6.6667
28,12.5,0.15,3.3333
29,13.2,0.15,0
30,6.0,0.00,21600
31,10.0,-0.02,21600
32,12.0,-0.05,21600
"""

def bootstrap_train_and_save() -> tuple[SGDRegressor, StandardScaler]:
    """
    Train initial model from embedded dataset, then save.
    """
    df = pd.read_csv(StringIO(BOOTSTRAP_CSV))
    df["level"] = pd.to_numeric(df["level"], errors="coerce")
    df["level_rate"] = pd.to_numeric(df["level_rate"], errors="coerce")
    df["time_to_danger_s"] = pd.to_numeric(df["time_to_danger_s"], errors="coerce")
    df = df.replace([np.inf, -np.inf], np.nan).dropna()

    X = df[["level", "level_rate"]].values.astype(float)
    y = df["time_to_danger_s"].values.astype(float)
    y = np.clip(y, 0.0, AI_S_MAX)

    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)

    model = SGDRegressor(
        loss="squared_error",
        penalty="l2",
        alpha=1e-4,
        learning_rate="invscaling",
        eta0=0.01,
        max_iter=40000,
        tol=1e-10,
        random_state=42
    )
    model.fit(Xs, y)

    dump(
        {
            "model": model,
            "scaler": scaler,
            "danger_level_cm": DANGER_LEVEL_CM,
            "features": [COL_LV, COL_LR],
            "note": "bootstrap trained from embedded dataset; online partial_fit enabled"
        },
        MODEL_PATH
    )
    return model, scaler

def load_or_bootstrap():
    if os.path.exists(MODEL_PATH):
        bundle = load(MODEL_PATH)
        return bundle["model"], bundle["scaler"]
    print("[AI] No model bundle found -> bootstrap training...")
    return bootstrap_train_and_save()

# =========================
# EXPORT existing telecsv rows immediately
# =========================
def export_existing_rows(model: SGDRegressor, scaler: StandardScaler):
    """
    Overwrite OUT_PATH with header, then write predictions for ALL existing rows.
    This guarantees you see ai_data_out.csv right away.
    """
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write("ts,level,level_rate,ai_s,risk_score\n")

    if not os.path.exists(TELECSV_PATH):
        print("[AI] telecsv not found yet -> export_existing_rows skipped.")
        return

    try:
        df = pd.read_csv(TELECSV_PATH)
    except Exception as e:
        print("[AI] cannot read telecsv:", e)
        return

    if COL_LV not in df.columns or COL_LR not in df.columns:
        print("[AI] telecsv missing required columns. Got:", list(df.columns))
        return

    df[COL_LV] = pd.to_numeric(df[COL_LV], errors="coerce")
    df[COL_LR] = pd.to_numeric(df[COL_LR], errors="coerce")
    df = df.replace([np.inf, -np.inf], np.nan).dropna(subset=[COL_LV, COL_LR]).copy()

    if len(df) == 0:
        print("[AI] telecsv has 0 valid rows -> nothing to export.")
        return

    X = df[[COL_LV, COL_LR]].values.astype(float)
    Xs = scaler.transform(X)

    ai_s = model.predict(Xs).astype(float)
    ai_s = np.array([clamp(float(x), 0.0, AI_S_MAX) for x in ai_s], dtype=float)
    risk = np.array([risk_score(float(x)) for x in ai_s], dtype=float)

    # Write rows
    with open(OUT_PATH, "a", encoding="utf-8") as f:
        for i in range(len(df)):
            ts = str(df.iloc[i].get(COL_TS, ""))
            lv = float(df.iloc[i][COL_LV])
            lr = float(df.iloc[i][COL_LR])
            f.write(f"{ts},{lv:.3f},{lr:.5f},{ai_s[i]:.3f},{risk[i]:.1f}\n")

    print(f"[AI] Exported existing rows: {len(df)} -> {OUT_PATH}")

# =========================
# FOLLOW telecsv.csv (append-only)
# =========================
def follow_csv_rows(path: str, sleep_s: float = FOLLOW_SLEEP):
    """
    Yields new raw lines appended AFTER current EOF.
    """
    while not os.path.exists(path):
        print(f"[WAIT] {path} not found yet...")
        time.sleep(1)

    with open(path, "r", encoding="utf-8") as f:
        # Skip header if present
        _ = f.readline()
        # Move to EOF so we only process NEW appended rows after start
        f.seek(0, os.SEEK_END)

        while True:
            line = f.readline()
            if not line:
                time.sleep(sleep_s)
                continue
            line = line.strip()
            if not line:
                continue
            yield line

# =========================
# MAIN
# =========================
def main():
    print("========== HYBRID ONLINE AI (CM DEMO) ==========")
    print("Input :", TELECSV_PATH)
    print("Output:", OUT_PATH)
    print("Model :", MODEL_PATH)
    print(f"DANGER_LEVEL_CM={DANGER_LEVEL_CM} | level_range={LEVEL_MIN}..{LEVEL_MAX}")
    print(f"ONLINE learn when rate>{MIN_RATE_FOR_LEARN} cm/s, batch={BATCH_SIZE}")

    model, scaler = load_or_bootstrap()
    print("[AI] Model ready.")

    # ✅ Export all existing rows immediately (so output file appears right away)
    export_existing_rows(model, scaler)

    # Online learning buffers
    buf_X = []
    buf_y = []

    # Realtime follow new rows
    for raw_line in follow_csv_rows(TELECSV_PATH):
        parsed = parse_csv_line(raw_line)
        if parsed is None:
            continue

        ts, level, rate = parsed

        # Sanity: keep in expected geometry range
        if not (LEVEL_MIN <= level <= LEVEL_MAX):
            continue

        # ---- PREDICT ----
        X = np.array([[level, rate]], dtype=float)
        Xs = scaler.transform(X)
        ai_s = float(model.predict(Xs)[0])
        ai_s = clamp(ai_s, 0.0, AI_S_MAX)
        risk = float(risk_score(ai_s))

        # ---- APPEND OUTPUT ----
        with open(OUT_PATH, "a", encoding="utf-8") as f:
            f.write(f"{ts},{level:.3f},{rate:.5f},{ai_s:.3f},{risk:.1f}\n")

        print(f"[AI] ts={ts} level={level:.2f}cm rate={rate:+.3f} -> ai_s={ai_s:.1f}s risk={risk:.0f}")

        # ---- ONLINE LEARNING (HYBRID) ----
        if rate > MIN_RATE_FOR_LEARN:
            y_phys = physics_pseudo_label(level, rate)
            buf_X.append([level, rate])
            buf_y.append(y_phys)

        if len(buf_X) >= BATCH_SIZE:
            Xb = np.array(buf_X, dtype=float)
            yb = np.array(buf_y, dtype=float)
            yb = np.clip(yb, 0.0, AI_S_MAX)

            Xb_s = scaler.transform(Xb)
            model.partial_fit(Xb_s, yb)

            dump(
                {
                    "model": model,
                    "scaler": scaler,
                    "danger_level_cm": DANGER_LEVEL_CM,
                    "features": [COL_LV, COL_LR],
                    "note": "bootstrap + online partial_fit (hybrid pseudo-label)"
                },
                MODEL_PATH
            )

            buf_X.clear()
            buf_y.clear()
            print("[AI] Online update done (partial_fit + saved bundle).")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[AI] stopped by user")
