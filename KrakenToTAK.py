import gpsd
import requests
import socket
import time
import json
import logging
import math
from datetime import datetime, timezone, timedelta
import random
from flask import Flask, render_template, request, jsonify
from threading import Thread, Lock

app = Flask(__name__)

CONFIG_FILE = 'config.json'
settings_lock = Lock()

# Settings (written under settings_lock; main loop snapshots under lock before use)
kraken_server = '0.0.0.0'
kraken_station = '1'
tak_server_ip = '0.0.0.0'
tak_server_port = '6666'
tak_multicast_state = True
start_angle = None
end_angle = None
persist_uid_line = False
line_distance = 6

# Live status tracking (written only from main loop, read by Flask status endpoint)
last_lat = None
last_lon = None
last_doa = None
packets_sent = 0
last_packet_time = None
kraken_reachable = False

# gpsd connection state
_gpsd_connected = False


def load_config():
    global kraken_server, kraken_station, tak_server_ip, tak_server_port
    global tak_multicast_state, start_angle, end_angle, persist_uid_line, line_distance
    try:
        with open(CONFIG_FILE, 'r') as f:
            cfg = json.load(f)
        kraken_server       = cfg.get('kraken_server',       kraken_server)
        kraken_station      = cfg.get('kraken_station',      kraken_station)
        tak_server_ip       = cfg.get('tak_server_ip',       tak_server_ip)
        tak_server_port     = cfg.get('tak_server_port',     tak_server_port)
        tak_multicast_state = cfg.get('tak_multicast_state', tak_multicast_state)
        start_angle         = cfg.get('start_angle',         start_angle)
        end_angle           = cfg.get('end_angle',           end_angle)
        persist_uid_line    = cfg.get('persist_uid_line',    persist_uid_line)
        line_distance       = cfg.get('line_distance',       line_distance)
        logging.info(f"Config loaded from {CONFIG_FILE}")
    except FileNotFoundError:
        logging.info("No config file found, using defaults")
    except Exception as e:
        logging.error(f"Error loading config: {e}")


def save_config():
    """Must be called while holding settings_lock."""
    try:
        cfg = {
            'kraken_server':       kraken_server,
            'kraken_station':      kraken_station,
            'tak_server_ip':       tak_server_ip,
            'tak_server_port':     tak_server_port,
            'tak_multicast_state': tak_multicast_state,
            'start_angle':         start_angle,
            'end_angle':           end_angle,
            'persist_uid_line':    persist_uid_line,
            'line_distance':       line_distance,
        }
        with open(CONFIG_FILE, 'w') as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        logging.error(f"Error saving config: {e}")


# Function to query Kraken Server
def url(_kraken_server):
    return "http://{0}:8081/DOA_value.html".format(_kraken_server)

# Function to calculate the second point
def calculate_second_point(lat1, lon1, bearing, distance):
    R = 6371  # Radius of the Earth in kilometers
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    angular_distance = distance / R
    lat2_rad = math.asin(math.sin(lat1_rad) * math.cos(angular_distance) +
                         math.cos(lat1_rad) * math.sin(angular_distance) * math.cos(math.radians(bearing)))
    lon2_rad = lon1_rad + math.atan2(math.sin(math.radians(bearing)) * math.sin(angular_distance) * math.cos(lat1_rad),
                                     math.cos(angular_distance) - math.sin(lat1_rad) * math.sin(lat2_rad))
    return math.degrees(lat2_rad), math.degrees(lon2_rad)

# Function to send CoT XML payload over UDP
def send_cot_payload(cot_xml_payload, server_ip, server_port):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_socket:
            udp_socket.sendto(cot_xml_payload.encode(), (server_ip, int(server_port)))
            logging.info(f"CoT XML Payload sent successfully to {server_ip}:{server_port}")
    except socket.error as e:
        logging.error(f"Socket error: takServerIp: {server_ip}")
        logging.error(f"Socket error: takServerPort: {server_port}")
        logging.error(f"Socket error: {e}")

# Function to send CoT XML payload to multicast endpoint
def send_to_multicast(cot_xml_payload_multicast):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_socket:
            udp_socket.sendto(cot_xml_payload_multicast.encode(), ('239.2.3.1', 6969))
            logging.info("CoT XML Payload sent to multicast endpoint 239.2.3.1:6969")
    except socket.error as e:
        logging.error(f"Socket error: {e}")

# Function to fetch raw Kraken server data once per loop iteration
def fetch_kraken_data(server):
    try:
        response = requests.get(url(server), timeout=5)
        return response.text.split(',')
    except requests.RequestException as e:
        logging.error(f"HTTP Request error fetching Kraken data: {e}")
        return None

# Function to get GPS data
def get_gps_data(kraken_data_parts=None):
    global _gpsd_connected
    try:
        if not _gpsd_connected:
            gpsd.connect()
            _gpsd_connected = True
        packet = gpsd.get_current()
        latitude = getattr(packet, 'lat', None)
        longitude = getattr(packet, 'lon', None)
        if latitude is not None and longitude is not None:
            return latitude, longitude
    except Exception as e:
        logging.error(f"Error connecting to GPSD: {e}")
        _gpsd_connected = False

    # Fall back to Kraken server GPS data if already fetched
    if kraken_data_parts is not None:
        try:
            return float(kraken_data_parts[8]), float(kraken_data_parts[9])
        except Exception as e:
            logging.error(f"Error using Kraken data for GPS: {e}")

    return None, None

# Function to create CoT XML payload for point feature
def create_cot_xml_payload_point(latitude, longitude, callsign, endpoint, phone, uid, group_name, group_role, geopointsrc, altsrc, battery, device, platform, os, version, speed, course):
    now = datetime.now(timezone.utc)
    ts = now.strftime('%Y-%m-%dT%H:%M:%S.995Z')
    ts_stale = (now + timedelta(seconds=75)).strftime('%Y-%m-%dT%H:%M:%S.995Z')
    return f'''<?xml version="1.0"?>
    <event version="2.0" uid="{kraken_station}-{uid}" type="a-f-G-U-C"
    time="{ts}"
    start="{ts}"
    stale="{ts_stale}"
    how="m-g">
        <point lat="{latitude}" lon="{longitude}" hae="999999" ce="35.0" le="999999" />
        <detail>
            <contact endpoint="{endpoint}" phone="{phone}" callsign="{callsign}" />
            <uid Droid="{callsign}" />
            <__group name="{group_name}" role="{group_role}" />
            <precisionlocation geopointsrc="{geopointsrc}" altsrc="{altsrc}" />
            <status battery="{battery}" />
            <takv device="{device}" platform="{platform}" os="{os}" version="{version}" />
            <track speed="{speed}" course="{course}" />
            <color argb="-256"/>
            <usericon iconsetpath="-256"/>
        </detail>
    </event>'''

# Function to create CoT XML payload for line feature
def create_cot_xml_payload_line(latitude_kraken, longitude_kraken, second_point, uid_line):
    now = datetime.now(timezone.utc)
    ts = now.strftime('%Y-%m-%dT%H:%M:%S.995Z')
    ts_stale = (now + timedelta(seconds=75)).strftime('%Y-%m-%dT%H:%M:%S.995Z')
    return f"""<?xml version='1.0' encoding='utf-8' standalone='yes'?>
        <event version='2.0' uid='{uid_line}' type='u-d-f' time='{ts}'
        start='{ts}'
        stale='{ts_stale}' how='h-e'>
            <point lat='{latitude_kraken}' lon='{longitude_kraken}' hae='999999' ce='35.0' le='999999'/>
            <point lat='{second_point[0]}' lon='{second_point[1]}' hae='999999' ce='35.0' le='999999'/>
            <detail>
                <link point='{latitude_kraken},{longitude_kraken}'/>
                <link point='{second_point[0]},{second_point[1]}'/>
                <__shapeExtras cpvis='true' editable='true'/>
                <__milsym id='10002500003406000000'/>
                <labels_on value='false'/>
                <archive/>
                <color value='-256'/>
                <contact callsign='CanaryTAK'/>
                <remarks></remarks>
                <strokeColor value='-256'/>
                <strokeWeight value='3.0'/>
                <strokeStyle value='solid'/>
            </detail>
        </event>
    """

# Function to generate uid_line with a random number every second
def generate_uid_line():
    return f'DOA-to-TAK-{random.randint(10000, 99999)}'

@app.route('/')
def index():
    return render_template('CanaryTAKDashboard.html')

@app.route('/status')
def status():
    _last_packet_time = last_packet_time  # atomic read under GIL
    ago = round(time.time() - _last_packet_time, 1) if _last_packet_time is not None else None
    return jsonify({
        'kraken_server': kraken_server,
        'kraken_station': kraken_station,
        'kraken_reachable': kraken_reachable,
        'tak_server_ip': tak_server_ip,
        'tak_server_port': tak_server_port,
        'tak_multicast': tak_multicast_state,
        'start_angle': start_angle,
        'end_angle': end_angle,
        'persist_uid_line': persist_uid_line,
        'line_distance': line_distance,
        'lat': last_lat,
        'lon': last_lon,
        'doa': last_doa,
        'packets_sent': packets_sent,
        'last_packet_ago': ago
    })

@app.route('/update_settings', methods=['POST'])
def update_settings():
    try:
        data = request.get_json()
        logging.info(f"Received settings: {data}")
        global persist_uid_line, kraken_server, kraken_station, tak_server_ip, tak_server_port, tak_multicast_state, start_angle, end_angle, line_distance

        with settings_lock:
            if 'persist_uid_line' in data:
                persist_uid_line = data['persist_uid_line']

            if 'kraken_server' in data:
                kraken_server = data['kraken_server']

            if 'kraken_station' in data:
                kraken_station = data['kraken_station']

            if 'tak_server_ip' in data:
                tak_server_ip = data['tak_server_ip']

            if 'tak_server_port' in data:
                tak_server_port = data['tak_server_port']

            if 'takMulticast' in data:
                tak_multicast_state = data['takMulticast']

            if 'line_distance' in data:
                line_distance = float(data['line_distance'])

            if 'start_angle' in data and 'end_angle' in data:
                if data['start_angle'] is None or data['end_angle'] is None:
                    start_angle = None
                    end_angle = None
                    save_config()
                    logging.info("DOA Ignore Range cleared")
                    return jsonify({"message": "DOA Ignore Range cleared"}), 200
                start_angle = float(data['start_angle'])
                end_angle = float(data['end_angle'])
                save_config()
                logging.info(f"Received DOA Ignore Range: {start_angle} to {end_angle}")
                return jsonify({"message": "DOA Ignore Range saved successfully"}), 200

            save_config()

        return 'Settings updated successfully'
    except Exception as e:
        logging.error(f"Error updating settings: {e}")
        return 'Failed to update settings'

def evaluate_angle_range(start_angle, end_angle, max_doa_angle):
    if start_angle is None or end_angle is None:
        logging.debug("No DOA Ignore wedge set")
        return True

    start_angle = int(start_angle) % 360
    end_angle = int(end_angle) % 360
    max_doa_angle = int(max_doa_angle) % 360

    if start_angle <= end_angle:
        if start_angle <= max_doa_angle <= end_angle:
            logging.debug("max doa angle between exclusion wedge.")
            return False
        return True
    else:
        if start_angle <= max_doa_angle or max_doa_angle <= end_angle:
            logging.debug("max doa angle between exclusion wedge.")
            return False
        return True

def run_flask():
    app.run(host='0.0.0.0', port=8000, use_reloader=False)

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    load_config()

    flask_thread = Thread(target=run_flask)
    flask_thread.start()

    while True:
        # Snapshot all settings under the lock for a consistent view this iteration
        with settings_lock:
            _kraken_server    = kraken_server
            _kraken_station   = kraken_station
            _tak_server_ip    = tak_server_ip
            _tak_server_port  = tak_server_port
            _tak_multicast    = tak_multicast_state
            _start_angle      = start_angle
            _end_angle        = end_angle
            _persist_uid_line = persist_uid_line
            _line_distance    = line_distance

        logging.info('Kraken server:' + _kraken_server)
        logging.info('Tak Server:' + _tak_server_ip + ':' + _tak_server_port)
        logging.info('Tak Multicast:' + str(_tak_multicast))

        # Fetch Kraken data once and reuse for GPS fallback and DOA line
        kraken_data_parts = fetch_kraken_data(_kraken_server)
        kraken_reachable = kraken_data_parts is not None

        if kraken_data_parts is None:
            last_doa = None

        latitude, longitude = get_gps_data(kraken_data_parts)
        last_lat = latitude
        last_lon = longitude

        any_sent = False

        if latitude is not None and longitude is not None:
            cot_xml_payload_point = create_cot_xml_payload_point(
                latitude, longitude, "Kraken Spot", "", "", f"{_kraken_station}-SignalMedic",
                "Yellow", "Team Member", "GPS", "", "", "", "", "", "", "0.00000000", ""
            )
            send_cot_payload(cot_xml_payload_point, _tak_server_ip, _tak_server_port)
            packets_sent += 1
            any_sent = True
            if _tak_multicast:
                send_to_multicast(cot_xml_payload_point)

            if kraken_data_parts is not None:
                try:
                    latitude_kraken = float(kraken_data_parts[8])
                    longitude_kraken = float(kraken_data_parts[9])
                    max_doa_angle = float(kraken_data_parts[1])
                    last_doa = max_doa_angle

                    logging.info(f"max_doa_angle: {max_doa_angle}")
                    logging.info(f"persist_uid_line: {_persist_uid_line}")

                    uid_line = generate_uid_line() if _persist_uid_line else f'{_kraken_station}-DOA-to-TAK'

                    if evaluate_angle_range(_start_angle, _end_angle, max_doa_angle):
                        logging.info("Sending payloads")
                        second_point = calculate_second_point(latitude_kraken, longitude_kraken, max_doa_angle, _line_distance)
                        cot_line_payload = create_cot_xml_payload_line(latitude_kraken, longitude_kraken, second_point, uid_line)
                        send_cot_payload(cot_line_payload, _tak_server_ip, _tak_server_port)
                        packets_sent += 1
                        any_sent = True
                        if _tak_multicast:
                            send_to_multicast(cot_line_payload)
                    else:
                        logging.info("Not sending payloads")

                except Exception as e:
                    logging.error(f"Error processing Kraken data: {e}")

        if any_sent:
            last_packet_time = time.time()

        time.sleep(5)
