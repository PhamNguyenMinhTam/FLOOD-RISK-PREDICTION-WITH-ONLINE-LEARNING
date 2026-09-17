#!/usr/bin/env python3
import os
import json
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

# =========================
# CONFIG (ENV first)
# =========================
MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "12A09/raw/telemetry")

# Path luu JSONL raw. Co the ghi de bang bien moi truong khi deploy.
CODE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(CODE_DIR))
JSONL_PATH = os.getenv(
    "JSONL_PATH",
    os.path.join(PROJECT_ROOT, "mqtt-data", "raw", "telemetry.jsonl"),
)

# InfluxDB v2 config
INFLUX_URL = os.getenv("INFLUX_URL", "http://127.0.0.1:8086")
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN", "")
INFLUX_ORG = os.getenv("INFLUX_ORG", "mworkste")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "12A09")
INFLUX_MEAS_RAW = os.getenv("INFLUX_MEAS_RAW", "telemetry_raw")

# Tags mặc định (bạn có thể để station cố định theo topic)
DEFAULT_STATION = os.getenv("STATION_ID", "12A09")
DEFAULT_DEVICE = os.getenv("DEVICE_ID", "esp32")

# Retry/backoff
RECONNECT_SLEEP = float(os.getenv("RECONNECT_SLEEP", "2.0"))

# =========================
# Influx client (global)
# =========================
influx_client = None
write_api = None


def ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)


def init_influx():
    global influx_client, write_api
    if not INFLUX_TOKEN or not INFLUX_ORG:
        print("[WARN] InfluxDB env missing (INFLUX_TOKEN/INFLUX_ORG). Will only save JSONL.")
        influx_client = None
        write_api = None
        return

    influx_client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG, timeout=30_000)
    write_api = influx_client.write_api(write_options=SYNCHRONOUS)
    print(f"[OK] InfluxDB ready: url={INFLUX_URL} org={INFLUX_ORG} bucket={INFLUX_BUCKET} meas={INFLUX_MEAS_RAW}")


def parse_station_from_topic(topic: str) -> str:
    # Topic dạng "12A09/raw/telemetry" => station = "12A09"
    try:
        parts = topic.split("/")
        if parts:
            return parts[0] or DEFAULT_STATION
    except Exception:
        pass
    return DEFAULT_STATION


def on_connect(client, userdata, flags, rc):
    print(f"[MQTT] connected rc={rc}, subscribing {MQTT_TOPIC}")
    client.subscribe(MQTT_TOPIC, qos=0)


def on_message(client, userdata, msg):
    # 1) decode payload
    try:
        payload = msg.payload.decode("utf-8", errors="strict")
    except Exception as e:
        print("[ERROR] decode payload:", e)
        return

    # 2) parse json
    try:
        data = json.loads(payload)
        if not isinstance(data, dict):
            print("[WARN] payload is not JSON object:", payload[:200])
            return
    except Exception as e:
        print("[ERROR] json.loads:", e, "payload:", payload[:200])
        return

    # 3) LƯU RAW JSONL (KHÔNG thêm _server_ts)
    try:
        ensure_parent_dir(JSONL_PATH)
        with open(JSONL_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
    except Exception as e:
        print("[ERROR] write jsonl:", e)

    # 4) GHI RAW VÀO INFLUXDB (nếu cấu hình đủ)
    if write_api is None:
        # Influx chưa bật => chỉ lưu file
        print("[RAW] saved_jsonl_only:", data)
        return

    # Expected payload:
    # {
    #   "ts_ms": 1766050125761,
    #   "metrics": {"level": 123.5, "level_rate": 0.85}
    # }
    ts_ms = data.get("ts_ms", None)
    metrics = data.get("metrics", {})
    if not isinstance(metrics, dict):
        metrics = {}

    level = metrics.get("level", None)
    level_rate = metrics.get("level_rate", None)

    # Validate minimal fields
    if ts_ms is None:
        # fallback: dùng time server nếu thiếu ts_ms (nhưng ESP32 bạn đang có ts_ms)
        ts_ms = int(time.time() * 1000)

    try:
        ts_ms = int(ts_ms)
    except Exception:
        ts_ms = int(time.time() * 1000)

    station = parse_station_from_topic(msg.topic)
    device = DEFAULT_DEVICE

    # Build Influx Point
    p = (
        Point(INFLUX_MEAS_RAW)
        .tag("station", station)
        .tag("device", device)
        .field("level", float(level) if level is not None else None)
        .field("level_rate", float(level_rate) if level_rate is not None else None)
        .time(ts_ms, WritePrecision.MS)
    )

    try:
        write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=p)
        print(f"[RAW->Influx] station={station} ts_ms={ts_ms} level={level} level_rate={level_rate}")
    except Exception as e:
        print("[ERROR] influx write:", e)


def main():
    init_influx()

    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message

    while True:
        try:
            print(f"[MQTT] connecting {MQTT_HOST}:{MQTT_PORT} ...")
            client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
            client.loop_forever()
        except KeyboardInterrupt:
            print("\n[EXIT] bye")
            break
        except Exception as e:
            print("[MQTT] connection loop error:", e)
            time.sleep(RECONNECT_SLEEP)


if __name__ == "__main__":
    main()
