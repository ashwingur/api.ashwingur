import os
import sys
from flask import request, jsonify
from datetime import datetime, timedelta
from app.weather import bp
from app.extensions import limiter, login_manager, db
from flask_login import login_required, current_user
from app.models.weather_data import insert_sensor_data, get_sensor_data_between_timestamps, get_latest_single_sensor_data
from app.extensions import roles_required
from zoneinfo import ZoneInfo

@bp.route('/', methods=['GET', 'POST'])
@limiter.limit("15/minute", override_defaults=True)
def sensor_data():
    if request.method == 'GET':
        # We expect a start and end timestamp, if none is given assume the latest data point
        # Expecting unix timestamp
        data = request.json
        if 'start' not in data and 'end' not in data:
            sensor_data = [get_latest_single_sensor_data()]
        elif 'start' in data and 'end' in data:
            start = datetime.fromtimestamp(data.get('start'), tz=ZoneInfo("UTC")) 
            end = datetime.fromtimestamp(data.get('end'), tz=ZoneInfo("UTC")) 
            sensor_data = get_sensor_data_between_timestamps(start, end)
        else:
            return jsonify({"success": False, 'error': "'start' and 'end' must both be provided, or not at all"}), 400

        headers = ['timestamp', 'temperature', 'pressure', 'humidity', 'ambient_light', 'air_quality_index', 'TVOC', 'eCO2']
        return jsonify({'headers': headers, 'data': sensor_data} ), 200
    elif request.method == 'POST':
        data = request.json

        if 'password' not in data:
            return jsonify({"success": False, 'error': 'password not provided'}), 400
        if data['password'] != os.environ.get('WEATHER_POST_PASSWORD'):
            print(f'password: {data["password"]}, actual: {os.environ.get("WEATHER_POST_PASSWORD")}', file=sys.stderr)
            return jsonify({"success": False, 'error': 'incorrect password'}), 400


        # Parse the incoming JSON data
        if 'timestamp' in data:
            timestamp = datetime.strptime(data['timestamp'], '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=ZoneInfo("UTC"))
        else:
            timestamp = datetime.now(ZoneInfo("UTC"))
        try:
            temperature = data['temperature']
            pressure = data['pressure']
            humidity = data['humidity']
            ambient_light = data['ambient_light']
            air_quality_index = data['air_quality_index']
            TVOC = data['TVOC']
            eCO2 = data['eCO2']
        except KeyError as e:
            return jsonify({'success': False, 'error': f"value not provided: {e}"}), 400



        insert_sensor_data(timestamp, temperature, pressure, humidity, ambient_light, air_quality_index, TVOC, eCO2)

        return jsonify({'success': True}), 201
