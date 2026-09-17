# 12A09 MQTT Telemetry and Flood Monitoring

Project thu thap du lieu muc nuoc tu ESP32 qua MQTT, luu tru du lieu tho, dong thoi dua du lieu vao InfluxDB de theo doi tren Grafana. He thong duoc thiet ke de chay tren Orange Pi/Raspberry Pi va cho phep ESP32 ket noi tu Internet qua MQTT over WebSocket Secure (WSS) va Cloudflare Tunnel.

## 1. Tong quan he thong

Luồng du lieu chinh:

```text
ESP32
  |
  | MQTT over WSS
  v
Cloudflare Edge (wss://12a09.mwork.group/)
  |
  | Cloudflare Tunnel
  v
Orange Pi/Raspberry Pi
  |
  +--> Mosquitto MQTT broker (WebSocket port 9001)
          |
          +--> mqtt_subscriber.py
                  |
                  +--> mqtt-data/raw/telemetry.jsonl
                  +--> InfluxDB v2
                  +--> json_to_csv.py
                          |
                          +--> mqtt-data/raw/telecsv.csv
```

Nguoi dung truy cap Grafana qua trinh duyet tren laptop, tablet hoac dien thoai. Grafana doc du lieu tu InfluxDB dang chay trong mang noi bo cua Orange Pi/Raspberry Pi; Cloudflare Tunnel cung cap duong truy cap HTTPS tu Internet vao giao dien can thiet.

## 2. Thanh phan

| Thanh phan | Vai tro |
| --- | --- |
| ESP32 | Do muc nuoc va phat telemetry JSON qua MQTT. |
| Cloudflare Edge | Nhan ket noi WSS tu ESP32 va chuyen tiep vao tunnel. |
| `cloudflared` | Tao ket noi outbound tu Orange Pi/Raspberry Pi den Cloudflare Edge. |
| Mosquitto | MQTT broker noi bo; WebSocket listener duoc dat tren port `9001` theo workflow. |
| `mqtt_subscriber.py` | Subscribe topic, ghi raw JSONL va ghi cac metric vao InfluxDB. |
| `json_to_csv.py` | Theo doi file JSONL va append du lieu hop le vao CSV. |
| InfluxDB v2 | Luu metric `level` va `level_rate` theo thoi gian. |
| Grafana | Hien thi dashboard va bieu do telemetry. |

## 3. Cau truc thu muc

```text
.
├── 12A09/
│   ├── mqtt-code/
│   │   ├── json_to_csv.py
│   │   ├── subscriber/
│   │   │   ├── mqtt_subscriber.py
│   │   │   └── .env
│   │   ├── data/raw/water_level.csv
│   │   ├── ai/
│   │   ├── grafana/
│   │   └── influxdb/
│   └── mqtt-data/
│       ├── raw/telemetry.jsonl
│       ├── raw/telecsv.csv
│       ├── raw/tele-sim.jsonl
│       └── processed/ai_data_out.csv
└── .gitignore
```

Ba thu muc `ai`, `grafana` va `influxdb` duoc giu trong cau truc project de phuc vu cac thanh phan tuong ung trong workflow. Snapshot hien tai khong co file cau hinh rieng duoc track trong cac thu muc nay; cac service can duoc cau hinh va chay rieng tren may chu.

## 4. Dinh dang telemetry

Payload MQTT duoc subscriber xu ly co dang:

```json
{
  "ts_ms": 1734500000000,
  "metrics": {
    "level": 123.5,
    "level_rate": 0.85
  }
}
```

- `ts_ms`: timestamp Unix tinh bang milliseconds.
- `metrics.level`: muc nuoc.
- `metrics.level_rate`: toc do thay doi muc nuoc.
- Topic mac dinh: `12A09/raw/telemetry`.

Subscriber luu nguyen payload JSON vao `12A09/mqtt-data/raw/telemetry.jsonl`. Neu cau hinh InfluxDB day du, subscriber ghi measurement `telemetry_raw` voi:

- Tags: `station`, `device`.
- Fields: `level`, `level_rate`.
- Timestamp: `ts_ms`, do chinh xac milliseconds.

## 5. Yeu cau moi truong

- Python 3.10+.
- Mosquitto MQTT broker.
- Python packages: `paho-mqtt` va `influxdb-client`.
- InfluxDB 2.x neu muon ghi du lieu vao database.
- Grafana neu muon tao dashboard.
- Cloudflare Tunnel neu can truy cap tu Internet qua domain WSS/HTTPS.

Cai package:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install paho-mqtt influxdb-client
```

Tren Windows, kich hoat moi truong bang:

```powershell
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
python -m pip install paho-mqtt influxdb-client
```

## 6. Cau hinh subscriber

Tao file `12A09/mqtt-code/subscriber/.env` hoac khai bao bien moi truong truoc khi chay:

```bash
export MQTT_HOST=127.0.0.1
export MQTT_PORT=1883
export MQTT_TOPIC=12A09/raw/telemetry
export INFLUX_URL=http://127.0.0.1:8086
export INFLUX_TOKEN=<influxdb-token>
export INFLUX_ORG=mworkste
export INFLUX_BUCKET=12A09
```

Cac gia tri mac dinh trong code:

| Bien | Mac dinh |
| --- | --- |
| `MQTT_HOST` | `127.0.0.1` |
| `MQTT_PORT` | `1883` |
| `MQTT_TOPIC` | `12A09/raw/telemetry` |
| `INFLUX_URL` | `http://127.0.0.1:8086` |
| `INFLUX_ORG` | `mworkste` |
| `INFLUX_BUCKET` | `12A09` |
| `INFLUX_MEAS_RAW` | `telemetry_raw` |
| `STATION_ID` | `12A09` |
| `DEVICE_ID` | `esp32` |
| `RECONNECT_SLEEP` | `2.0` giay |

Khong commit token InfluxDB vao repository. Neu token da tung bi lo, hay thu hoi va tao token moi trong InfluxDB.

## 7. Chay MQTT subscriber

Tu thu muc goc repository:

```bash
cd 12A09/mqtt-code/subscriber
python3 mqtt_subscriber.py
```

Khi khoi dong, chuong trinh:

1. Khoi tao ket noi InfluxDB neu co `INFLUX_TOKEN` va `INFLUX_ORG`.
2. Ket noi den MQTT broker.
3. Subscribe topic `12A09/raw/telemetry`.
4. Parse payload JSON va ghi tung message vao file JSONL.
5. Ghi `level` va `level_rate` vao InfluxDB neu InfluxDB da duoc cau hinh.
6. Tu dong thu lai ket noi sau loi voi khoang nghi `RECONNECT_SLEEP`.

Duong dan JSONL trong code hien tai la:

```text
/home/mpi5iot/Desktop/12A09/mqtt-data/raw/telemetry.jsonl
```

Khi chay tren may khac, cap nhat `JSONL_PATH` trong `mqtt_subscriber.py` cho phu hop voi duong dan repository tren may do.

## 8. Chuyen JSONL sang CSV

`json_to_csv.py` doc file `12A09/mqtt-data/raw/telemetry.jsonl` va theo doi them dong moi nhu `tail -f`. Ket qua duoc append vao:

```text
12A09/mqtt-data/raw/telecsv.csv
```

Chay tu thu muc goc repository:

```bash
python3 12A09/mqtt-code/json_to_csv.py
```

Mac dinh, chuong trinh chi xu ly du lieu duoc ghi sau thoi diem khoi dong. De xu ly tu dau file roi tiep tuc theo doi:

```bash
START_FROM_BEGIN=1 python3 12A09/mqtt-code/json_to_csv.py
```

De xoa CSV cu truoc khi chay:

```bash
RESET_CSV=1 python3 12A09/mqtt-code/json_to_csv.py
```

CSV co ba cot:

```text
ts,level,level_rate
```

## 9. Cloudflare Tunnel va WSS

Theo workflow, ESP32 ket noi den domain:

```text
wss://12a09.mwork.group/
```

`cloudflared` chay tren Orange Pi/Raspberry Pi va duy tri ket noi outbound den Cloudflare Edge. Tunnel route luong WSS ve Mosquitto WebSocket listener trong mang noi bo, du kien tren port `9001`.

Can dam bao:

- DNS hostname `12a09.mwork.group` tro ve Cloudflare.
- Cloudflare Tunnel dang chay tren may chu.
- Mosquitto da bat WebSocket listener va port listener khop voi tunnel.
- Firewall cho phep ket noi noi bo giua `cloudflared` va Mosquitto.
- ESP32 dung dung hostname, port va TLS configuration cua tunnel.

## 10. InfluxDB va Grafana

Subscriber ghi measurement `telemetry_raw` vao bucket `12A09`. Trong Grafana:

1. Them InfluxDB v2 data source.
2. Khai bao URL, organization, bucket va token tuong ung.
3. Truy van cac field `level` va `level_rate` theo timestamp.
4. Tao panel bieu do muc nuoc, toc do thay doi va canh bao.

Grafana co the duoc expose qua HTTPS/Cloudflare de nguoi dung xem dashboard tu laptop, tablet hoac smartphone ma khong can mo truc tiep port InfluxDB ra Internet.

## 11. Kiem tra nhanh

Kiem tra file raw co duoc ghi:

```bash
tail -f 12A09/mqtt-data/raw/telemetry.jsonl
```

Kiem tra CSV:

```bash
tail -f 12A09/mqtt-data/raw/telecsv.csv
```

Kiem tra topic MQTT tu may chay broker:

```bash
mosquitto_sub -h 127.0.0.1 -p 1883 -t 12A09/raw/telemetry -v
```

Kiem tra subscriber co dang chay:

```bash
ps aux | grep mqtt_subscriber.py
```

## 12. Xu ly su co

| Hien tuong | Kiem tra |
| --- | --- |
| Subscriber khong ket noi MQTT | Kiem tra `MQTT_HOST`, `MQTT_PORT`, broker va topic. |
| Co JSONL nhung khong co InfluxDB data | Kiem tra `INFLUX_URL`, `INFLUX_TOKEN`, `INFLUX_ORG`, bucket va log loi cua subscriber. |
| CSV khong cap nhat | Kiem tra duong dan `telemetry.jsonl`, quyen ghi va chay `json_to_csv.py`. |
| ESP32 khong vao duoc WSS | Kiem tra DNS, Cloudflare Tunnel, TLS hostname va WebSocket listener cua Mosquitto. |
| Grafana khong hien thi data | Kiem tra data source, bucket, organization, measurement va time range. |