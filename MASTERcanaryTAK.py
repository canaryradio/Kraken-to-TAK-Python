import gpsd
import requests
import xml.etree.ElementTree as ET
import socket
import time
import logging
import math
import datetime
from flask import Flask, render_template, request
from threading import Thread

app = Flask(__name__)

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
    lat2 = math.degrees(lat2_rad)
    lon2 = math.degrees(lon2_rad)
    return lat2, lon2

# Function to send CoT XML payload over UDP
def send_cot_payload(cot_xml_payload):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_socket:
            udp_socket.sendto(cot_xml_payload.encode(), ("239.2.3.1", 6969))
            logging.info("CoT XML Payload sent successfully")
    except socket.error as e:
        logging.error(f"Socket error: {e}")

# Function to get GPS data
def get_gps_data():
    try:
        gpsd.connect()
        packet = gpsd.get_current()
        latitude = getattr(packet, 'lat', None)
        longitude = getattr(packet, 'lon', None)
        return latitude, longitude
    except Exception as e:
        logging.error(f"Error getting GPS data: {e}")
        return None, None

# Function to create CoT XML payload for point feature
def create_cot_xml_payload_point(latitude, longitude, hae, ce, le, callsign, endpoint, phone, uid, group_name, group_role, geopointsrc, altsrc, battery, device, platform, os, version, speed, course):
    return f'''<?xml version="1.0"?>
    <event version="2.0" uid="{uid}" type="a-f-G-U-C"
    time="{datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.995Z')}"
    start="{datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.995Z')}"
    stale="{(datetime.datetime.utcnow() + datetime.timedelta(seconds=75)).strftime('%Y-%m-%dT%H:%M:%S.995Z')}"
    how="m-g">
        <point lat="{latitude}" lon="{longitude}" hae="{hae}" ce="{ce}" le="{le}" />
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
def create_cot_xml_payload_line(latitude, longitude, second_point, uid):
    return f"""<?xml version='1.0' encoding='utf-8' standalone='yes'?>
        <event version='2.0' uid='{uid}' type='u-d-f' time='{datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.995Z')}'
        start='{datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.995Z')}'
        stale='{(datetime.datetime.utcnow() + datetime.timedelta(seconds=75)).strftime('%Y-%m-%dT%H:%M:%S.995Z')}' how='h-e'>
            <point lat='{latitude}' lon='{longitude}' hae='999999' ce='35.0' le='999999'/>
            <point lat='{second_point[0]}' lon='{second_point[1]}' hae='999999' ce='35.0' le='999999'/>
            <detail>
                <link point='{latitude},{longitude}'/>
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

@app.route('/')
def index():
    return render_template('CanaryTAKDashboard.html')

@app.route('/update_settings', methods=['POST'])
def update_settings():
    # Extract parameters from the POST request
    persist_doa_line = request.form.get('persist_doa_line')
    kraken_server = request.form.get('kraken_server')
    tak_server_ip = request.form.get('tak_server_ip')
    tak_server_port = request.form.get('tak_server_port')
    
    return 'Settings updated successfully'

def run_flask():
    if __name__ == '__main__':
        app.run(host='0.0.0.0', port=8000)
    app.run(debug=True, use_reloader=False)

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    udp_ip = "239.2.3.1"
    udp_port = 6969
    default_ce = 9999999
    default_hae = 9999999
    default_le = 9999999

    # Start Flask in a separate thread
    flask_thread = Thread(target=run_flask)
    flask_thread.start()

    while True:
        # Get GPS data
        latitude, longitude = get_gps_data()

        if latitude is not None and longitude is not None:
            # Point feature
            callsign_point = "Kraken Spot"
            endpoint_point = ""
            phone_point = ""
            uid_point = "Router-to-TAK"
            group_name_point = "Yellow"
            group_role_point = "Team Member"
            geopointsrc_point = "GPS"
            altsrc_point = ""
            battery_point = ""
            device_point = ""
            platform_point = ""
            os_point = ""
            version_point = ""
            speed_point = "0.00000000"
            course_point = ""

            cot_xml_payload_point = create_cot_xml_payload_point(latitude, longitude, default_hae, default_ce, default_le,
                                                                callsign_point, endpoint_point, phone_point, uid_point,
                                                                group_name_point, group_role_point, geopointsrc_point,
                                                                altsrc_point, battery_point, device_point, platform_point,
                                                                os_point, version_point, speed_point, course_point)
            send_cot_payload(cot_xml_payload_point)

            # Line feature
            try:
                kraken_response = requests.get("http://10.0.0.16:8081/DOA_value.html")
                kraken_data = kraken_response.text

                data_parts = kraken_data.split(',')
                latitude_kraken = float(data_parts[8])
                longitude_kraken = float(data_parts[9])
                max_doa_angle = float(data_parts[1])

                second_point = calculate_second_point(latitude_kraken, longitude_kraken, max_doa_angle, 6)

                uid_line = 'DOA-to-TAK'
                cot_line_payload = create_cot_xml_payload_line(latitude_kraken, longitude_kraken, second_point, uid_line)

                send_cot_payload(cot_line_payload)

            except requests.RequestException as e:
                logging.error(f"HTTP Request error: {e}")
            except Exception as e:
                logging.error(f"Error: {e}")

        time.sleep(5)