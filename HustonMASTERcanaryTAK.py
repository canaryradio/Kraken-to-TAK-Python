import gpsd
import requests
import xml.etree.ElementTree as ET
import socket
import time
import logging
import math
import datetime
import random
from flask import Flask, render_template, request, jsonify
from threading import Thread

app = Flask(__name__)

kraken_server = '0.0.0.0'
tak_server_ip = '0.0.0.0'
tak_server_port = '6666'
tak_multicast_state = True
default_hae = 999999
default_ce = 35.0
default_le = 999999
start_angle = None
end_angle = None
persist_uid_line = None

# Function to query kraken Server
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
    lat2 = math.degrees(lat2_rad)
    lon2 = math.degrees(lon2_rad)
    return lat2, lon2

# Function to send CoT XML payload over UDP
def send_cot_payload(cot_xml_payload):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_socket:
            udp_socket.sendto(cot_xml_payload.encode(), (tak_server_ip, int(tak_server_port)))
            logging.info(f"CoT XML Payload sent successfully to {tak_server_ip}:{tak_server_port}")
    except socket.error as e:
        logging.error(f"Socket error: takServerIp: {tak_server_ip}")
        logging.error(f"Socket error: takServerPort: {tak_server_port}")
        logging.error(f"Socket error: {e}")

# Function to send CoT XML payload to multicast endpoint
def send_to_multicast(cot_xml_payload_multicast):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_socket:
            udp_socket.sendto(cot_xml_payload_multicast.encode(), ('239.2.3.1', 6969))
            logging.info(f"CoT XML Payload sent to multicast endpoint 239.2.3.1:6969")
    except socket.error as e:
        logging.error(f"Socket error: {e}")

import requests  # Import requests module

# Function to get GPS data
def get_gps_data():
    try:
        gpsd.connect()
        packet = gpsd.get_current()
        latitude = getattr(packet, 'lat', None)
        longitude = getattr(packet, 'lon', None)

        # If GPSD data is available, return it
        if latitude is not None and longitude is not None:
            return latitude, longitude
        
    except Exception as e:
        # Log any errors encountered while connecting to GPSD
        logging.error(f"Error connecting to GPSD: {e}")

    # If GPSD is not available or encountered an error, use alternate source (if available)
    try:
        # Fetch data from Kraken server
        kraken_response = requests.get(url(kraken_server))
        kraken_data = kraken_response.text

        # Split the data and extract latitude and longitude
        data_parts = kraken_data.split(',')
        latitude_kraken = float(data_parts[8])
        longitude_kraken = float(data_parts[9])
        
        # If alternate source data is available, return it
        return latitude_kraken, longitude_kraken
    
    except Exception as e:
        # Log any errors encountered while using alternate source
        logging.error(f"Error using alternate source for GPS data: {e}")

    # If both GPSD and alternate source fail, return None
    return None, None

# Function to create CoT XML payload for point feature
def create_cot_xml_payload_point(latitude, longitude, callsign, endpoint, phone, uid, group_name, group_role, geopointsrc, altsrc, battery, device, platform, os, version, speed, course):
    return f'''<?xml version="1.0"?>
    <event version="2.0" uid="{uid}" type="a-f-G-U-C"
    time="{datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.995Z')}"
    start="{datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.995Z')}"
    stale="{(datetime.datetime.utcnow() + datetime.timedelta(seconds=75)).strftime('%Y-%m-%dT%H:%M:%S.995Z')}"
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
    return f"""<?xml version='1.0' encoding='utf-8' standalone='yes'?>
        <event version='2.0' uid='{uid_line}' type='u-d-f' time='{datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.995Z')}'
        start='{datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.995Z')}'
        stale='{(datetime.datetime.utcnow() + datetime.timedelta(seconds=75)).strftime('%Y-%m-%dT%H:%M:%S.995Z')}' how='h-e'>
            <point lat='{latitude_kraken}' lon='{longitude_kraken}' hae='999999' ce='35.0' le='999999'/>
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
# Function to generate uid_line with a random number every second
def generate_uid_line():
    uid_line = f'DOA-to-TAK-{random.randint(1000, 9999)}'
    return uid_line 

@app.route('/')
def index():
    return render_template('CanaryTAKDashboard.html')

@app.route('/update_settings', methods=['POST'])
def update_settings():
    try:
        foobar = request.get_json()
        logging.info(f"Received settings: {foobar}")
        # Extract parameters from the POST request
        global persist_uid_line, kraken_server, tak_server_ip, tak_server_port, tak_multicast_state, start_angle, end_angle
        
        if 'persist_uid_line' in foobar:
            persist_uid_line = foobar['persist_uid_line']
        
        if 'kraken_server' in foobar:
            kraken_server = foobar['kraken_server']
        
        if 'tak_server_ip' in foobar:
            tak_server_ip = foobar['tak_server_ip']

        if 'tak_server_port' in foobar:
            tak_server_port = foobar['tak_server_port']

        if 'takMulticast' in foobar:
            tak_multicast_state = foobar['takMulticast']

        if 'start_angle' in foobar and 'end_angle' in foobar:
            start_angle = float(foobar['start_angle'])
            end_angle = float(foobar['end_angle'])
            logging.info(f"Received DOA Ignore Range: {start_angle} to {end_angle}")
            return jsonify({"message": "DOA Ignore Range saved successfully"}), 200

        return 'Settings updated successfully'
    except Exception as e:
        logging.error(f"Error updating settings: {e}")
        return 'Failed to update settings'

def evaluate_angle_range(start_angle, end_angle, max_doa_angle):
    if start_angle is not None and end_angle is not None:
        # Convert strings to integers, and ensure they are between 0 and 359
        start_angle = int(start_angle) % 360
        end_angle = int(end_angle) % 360
        max_doa_angle = int(max_doa_angle) % 360

        if start_angle <= end_angle:
            # Case where end_angle is greater than or equal to start_angle
            if start_angle <= max_doa_angle <= end_angle:
                print("max doa angle between exclusion wedge.")
                return False
            else:
                print("sending payloads")
                return True
        else:
            # Case where end_angle wraps around to less than start_angle
            if start_angle <= max_doa_angle or max_doa_angle <= end_angle:
                print("max doa angle between exclusion wedge.")
                return False
            else:
                print("sending payloads")
                return True
    else:
        print("No DOA Ignore wedge set")
        return True

def run_flask():
    if __name__ == '__main__':
        app.run(host='0.0.0.0', port=8000)
    app.run(debug=True, use_reloader=False)

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    # Start Flask in a separate thread
    flask_thread = Thread(target=run_flask)
    flask_thread.start()

    while True:
        logging.info('Kraken server:' + kraken_server)
        logging.info('Tak Server:' + tak_server_ip + ':' + tak_server_port)       
        logging.info('Tak Multicast:' + str(tak_multicast_state))
        
        # Get GPS data
        latitude, longitude = get_gps_data()

        if latitude is not None and longitude is not None:
            # Point feature
            callsign_point = "Kraken Spot"
            endpoint_point = ""
            phone_point = ""
            uid_point = "SignalMedic"
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
            
            cot_xml_payload_point = create_cot_xml_payload_point(
                latitude, longitude, callsign_point, endpoint_point, phone_point, uid_point,
                group_name_point, group_role_point, geopointsrc_point,
                altsrc_point, battery_point, device_point, platform_point,
                os_point, version_point, speed_point, course_point
            )


            send_cot_payload(cot_xml_payload_point)
            # Send to Multicast endpoint if takMulticast is True
            if tak_multicast_state:
                send_to_multicast(cot_xml_payload_point)

            # Line feature
            try:
                kraken_response = requests.get(url(kraken_server))
                kraken_data = kraken_response.text

                data_parts = kraken_data.split(',')
                latitude_kraken = float(data_parts[8])
                longitude_kraken = float(data_parts[9])
                max_doa_angle = float(data_parts[1])

                logging.info(f"max_doa_angle: {max_doa_angle}")
                logging.info(f"persist_uid_line: {persist_uid_line}")
                if persist_uid_line is True:
                    uid_line = generate_uid_line()
                else:
                    uid_line = 'DOA-to-TAK'

                if start_angle is not None and end_angle is not None:
                    if evaluate_angle_range(start_angle, end_angle, max_doa_angle):
                        logging.info("Sending payloads")
                        second_point = calculate_second_point(latitude_kraken, longitude_kraken, max_doa_angle, 6)
                        cot_line_payload = create_cot_xml_payload_line(latitude_kraken, longitude_kraken, second_point, uid_line)
                        send_cot_payload(cot_line_payload)
                        if tak_multicast_state:
                            send_to_multicast(cot_line_payload)
                    else:
                        logging.info("Not sending payloads")
                else:
                    logging.info(f"No DOA Ignore wedge set")
                    second_point = calculate_second_point(latitude_kraken, longitude_kraken, max_doa_angle, 6)
                    
                    cot_line_payload = create_cot_xml_payload_line(latitude_kraken, longitude_kraken, second_point, uid_line)

                    send_cot_payload(cot_line_payload)

                    # Send to Multicast endpoint if takMulticast is True
                    if tak_multicast_state:
                        send_to_multicast(cot_line_payload)

            except requests.RequestException as e:
                logging.error(f"HTTP Request error: {e}")
            except Exception as e:
                logging.error(f"Error: {e}")

        time.sleep(5)