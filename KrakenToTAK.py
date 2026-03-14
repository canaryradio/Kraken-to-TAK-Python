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

# Per-server settings live inside kraken_servers list entries:
#   {ip, station, start_angle, end_angle, persist_uid_line, line_distance}
kraken_servers = [{'ip': '0.0.0.0', 'station': '1',
                   'start_angle': None, 'end_angle': None,
                   'persist_uid_line': False, 'line_distance': 6}]

# Shared TAK destination settings
tak_server_ip = '0.0.0.0'
tak_server_port = '6666'
tak_multicast_state = True

# Live status: list of dicts mirroring kraken_servers order, rebuilt each loop
server_statuses = []
packets_sent = 0
last_packet_time = None

# gpsd connection state
_gpsd_connected = False


def _default_server(ip='0.0.0.0', station='1'):
    return {'ip': ip, 'station': station,
            'start_angle': None, 'end_angle': None,
            'persist_uid_line': False, 'line_distance': 6}


def load_config():
    global kraken_servers, tak_server_ip, tak_server_port, tak_multicast_state
    try:
        with open(CONFIG_FILE, 'r') as f:
            cfg = json.load(f)

        # Migrate legacy single-server flat format
        if 'kraken_server' in cfg and 'kraken_servers' not in cfg:
            srv = _default_server(cfg['kraken_server'], cfg.get('kraken_station', '1'))
            srv['start_angle']      = cfg.get('start_angle')
            srv['end_angle']        = cfg.get('end_angle')
            srv['persist_uid_line'] = cfg.get('persist_uid_line', False)
            srv['line_distance']    = cfg.get('line_distance', 6)
            kraken_servers = [srv]
        else:
            raw = cfg.get('kraken_servers', kraken_servers)
            # Ensure every entry has all expected keys
            kraken_servers = [dict(_default_server(), **s) for s in raw]

        tak_server_ip       = cfg.get('tak_server_ip',       tak_server_ip)
        tak_server_port     = cfg.get('tak_server_port',     tak_server_port)
        tak_multicast_state = cfg.get('tak_multicast_state', tak_multicast_state)
        logging.info(f"Config loaded from {CONFIG_FILE}")
    except FileNotFoundError:
        logging.info("No config file found, using defaults")
    except Exception as e:
        logging.error(f"Error loading config: {e}")


def save_config():
    """Must be called while holding settings_lock."""
    try:
        cfg = {
            'kraken_servers':      kraken_servers,
            'tak_server_ip':       tak_server_ip,
            'tak_server_port':     tak_server_port,
            'tak_multicast_state': tak_multicast_state,
        }
        with open(CONFIG_FILE, 'w') as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        logging.error(f"Error saving config: {e}")


def url(_kraken_server):
    return "http://{0}:8081/DOA_value.html".format(_kraken_server)

def calculate_second_point(lat1, lon1, bearing, distance):
    R = 6371
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    angular_distance = distance / R
    lat2_rad = math.asin(math.sin(lat1_rad) * math.cos(angular_distance) +
                         math.cos(lat1_rad) * math.sin(angular_distance) * math.cos(math.radians(bearing)))
    lon2_rad = lon1_rad + math.atan2(math.sin(math.radians(bearing)) * math.sin(angular_distance) * math.cos(lat1_rad),
                                     math.cos(angular_distance) - math.sin(lat1_rad) * math.sin(lat2_rad))
    return math.degrees(lat2_rad), math.degrees(lon2_rad)

def send_cot_payload(cot_xml_payload, server_ip, server_port):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_socket:
            udp_socket.sendto(cot_xml_payload.encode(), (server_ip, int(server_port)))
            logging.info(f"CoT XML Payload sent successfully to {server_ip}:{server_port}")
    except socket.error as e:
        logging.error(f"Socket error: takServerIp: {server_ip}")
        logging.error(f"Socket error: takServerPort: {server_port}")
        logging.error(f"Socket error: {e}")

def send_to_multicast(cot_xml_payload_multicast):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_socket:
            udp_socket.sendto(cot_xml_payload_multicast.encode(), ('239.2.3.1', 6969))
            logging.info("CoT XML Payload sent to multicast endpoint 239.2.3.1:6969")
    except socket.error as e:
        logging.error(f"Socket error: {e}")

def fetch_kraken_data(server):
    try:
        response = requests.get(url(server), timeout=5)
        return response.text.split(',')
    except requests.RequestException as e:
        logging.error(f"HTTP Request error fetching Kraken data from {server}: {e}")
        return None

def get_gps_data(kraken_data_parts=None):
    global _gpsd_connected
    try:
        if not _gpsd_connected:
            gpsd.connect()
            _gpsd_connected = True
        packet = gpsd.get_current()
        latitude  = getattr(packet, 'lat', None)
        longitude = getattr(packet, 'lon', None)
        if latitude is not None and longitude is not None:
            return latitude, longitude
    except Exception as e:
        logging.error(f"Error connecting to GPSD: {e}")
        _gpsd_connected = False

    if kraken_data_parts is not None:
        try:
            return float(kraken_data_parts[8]), float(kraken_data_parts[9])
        except Exception as e:
            logging.error(f"Error using Kraken data for GPS: {e}")

    return None, None

def create_cot_xml_payload_point(latitude, longitude, callsign, endpoint, phone, uid, group_name, group_role, geopointsrc, altsrc, battery, device, platform, os, version, speed, course, station_id):
    now = datetime.now(timezone.utc)
    ts = now.strftime('%Y-%m-%dT%H:%M:%S.995Z')
    ts_stale = (now + timedelta(seconds=75)).strftime('%Y-%m-%dT%H:%M:%S.995Z')
    return f'''<?xml version="1.0"?>
    <event version="2.0" uid="{station_id}-{uid}" type="a-f-G-U-C"
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

def generate_uid_line(station):
    return f'{station}-DOA-to-TAK-{random.randint(10000, 99999)}'


def evaluate_angle_range(start_angle, end_angle, max_doa_angle):
    if start_angle is None or end_angle is None:
        return True

    start_angle   = int(start_angle)   % 360
    end_angle     = int(end_angle)     % 360
    max_doa_angle = int(max_doa_angle) % 360

    if start_angle <= end_angle:
        return not (start_angle <= max_doa_angle <= end_angle)
    else:
        return not (start_angle <= max_doa_angle or max_doa_angle <= end_angle)


@app.route('/')
def index():
    return render_template('CanaryTAKDashboard.html')

@app.route('/status')
def status():
    _last_packet_time = last_packet_time
    ago = round(time.time() - _last_packet_time, 1) if _last_packet_time is not None else None

    _servers  = kraken_servers   # atomic reference read
    _statuses = server_statuses  # atomic reference read

    servers_out = []
    for i, srv in enumerate(_servers):
        live = _statuses[i] if i < len(_statuses) else {}
        servers_out.append({
            'ip':             srv.get('ip'),
            'station':        srv.get('station'),
            'start_angle':    srv.get('start_angle'),
            'end_angle':      srv.get('end_angle'),
            'persist_uid_line': srv.get('persist_uid_line', False),
            'line_distance':  srv.get('line_distance', 6),
            'reachable':      live.get('reachable', False),
            'lat':            live.get('lat'),
            'lon':            live.get('lon'),
            'doa':            live.get('doa'),
        })

    return jsonify({
        'servers':        servers_out,
        'tak_server_ip':  tak_server_ip,
        'tak_server_port': tak_server_port,
        'tak_multicast':  tak_multicast_state,
        'packets_sent':   packets_sent,
        'last_packet_ago': ago,
    })

@app.route('/update_settings', methods=['POST'])
def update_settings():
    try:
        data = request.get_json()
        logging.info(f"Received settings: {data}")
        global kraken_servers, tak_server_ip, tak_server_port, tak_multicast_state

        with settings_lock:
            if 'kraken_servers' in data:
                # Ensure every entry has all expected keys
                kraken_servers = [dict(_default_server(), **s) for s in data['kraken_servers']]

            if 'tak_server_ip' in data:
                tak_server_ip = data['tak_server_ip']

            if 'tak_server_port' in data:
                tak_server_port = data['tak_server_port']

            if 'takMulticast' in data:
                tak_multicast_state = data['takMulticast']

            save_config()

        return 'Settings updated successfully'
    except Exception as e:
        logging.error(f"Error updating settings: {e}")
        return 'Failed to update settings'


def run_flask():
    app.run(host='0.0.0.0', port=8000, use_reloader=False)

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    load_config()

    flask_thread = Thread(target=run_flask)
    flask_thread.start()

    while True:
        with settings_lock:
            _servers         = list(kraken_servers)
            _tak_server_ip   = tak_server_ip
            _tak_server_port = tak_server_port
            _tak_multicast   = tak_multicast_state

        logging.info(f"Polling {len(_servers)} Kraken server(s)")
        logging.info(f"TAK Server: {_tak_server_ip}:{_tak_server_port}  Multicast: {_tak_multicast}")

        statuses  = []
        any_sent  = False

        for srv in _servers:
            _ip             = srv['ip']
            _station        = srv['station']
            _start_angle    = srv.get('start_angle')
            _end_angle      = srv.get('end_angle')
            _persist        = srv.get('persist_uid_line', False)
            _line_distance  = srv.get('line_distance', 6)

            kraken_data_parts = fetch_kraken_data(_ip)
            reachable = kraken_data_parts is not None

            latitude, longitude, doa = None, None, None

            if reachable:
                latitude, longitude = get_gps_data(kraken_data_parts)

                if latitude is not None and longitude is not None:
                    cot_xml_payload_point = create_cot_xml_payload_point(
                        latitude, longitude, "Kraken Spot", "", "", "SignalMedic",
                        "Yellow", "Team Member", "GPS", "", "", "", "", "", "", "0.00000000", "",
                        station_id=_station
                    )
                    send_cot_payload(cot_xml_payload_point, _tak_server_ip, _tak_server_port)
                    packets_sent += 1
                    any_sent = True
                    if _tak_multicast:
                        send_to_multicast(cot_xml_payload_point)

                    try:
                        latitude_kraken  = float(kraken_data_parts[8])
                        longitude_kraken = float(kraken_data_parts[9])
                        doa              = float(kraken_data_parts[1])

                        logging.info(f"[{_station}] DOA: {doa}")

                        uid_line = generate_uid_line(_station) if _persist else f'{_station}-DOA-to-TAK'

                        if evaluate_angle_range(_start_angle, _end_angle, doa):
                            logging.info(f"[{_station}] Sending DOA line payload")
                            second_point = calculate_second_point(latitude_kraken, longitude_kraken, doa, _line_distance)
                            cot_line_payload = create_cot_xml_payload_line(latitude_kraken, longitude_kraken, second_point, uid_line)
                            send_cot_payload(cot_line_payload, _tak_server_ip, _tak_server_port)
                            packets_sent += 1
                            any_sent = True
                            if _tak_multicast:
                                send_to_multicast(cot_line_payload)
                        else:
                            logging.info(f"[{_station}] DOA suppressed by exclusion range")

                    except Exception as e:
                        logging.error(f"Error processing Kraken data for {_ip}: {e}")

            statuses.append({
                'ip':        _ip,
                'station':   _station,
                'reachable': reachable,
                'lat':       latitude,
                'lon':       longitude,
                'doa':       doa,
            })

        server_statuses = statuses  # atomic replacement under GIL

        if any_sent:
            last_packet_time = time.time()

        time.sleep(5)
