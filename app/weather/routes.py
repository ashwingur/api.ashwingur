from flask import request, jsonify
from datetime import datetime, timedelta
from app.weather import bp
from app.extensions import limiter, login_manager, db
from flask_login import login_required, current_user
from app.models.weather_data import insert_sensor_data, get_all_sensor_data, execute_sensor_query, get_sensor_data_between_timestamps
from app.extensions import roles_required

@bp.route('/', methods=['GET', 'POST'])
@limiter.limit("30/minute", override_defaults=True)
@login_required
@roles_required('user', 'admin')
def users():
    if request.method == 'GET':
        # We expect a start and end timestamp, if none is given assume last 24 hours
        # Expecting unix timestamp
        data = request.json
        if 'start' not in data and 'end' not in data:
            start = datetime.now()
            end = datetime.now() - timedelta(days=1)
        else:
            start = datetime.utcfromtimestamp(data.get('start')) 
            end = datetime.utcfromtimestamp(data.get('end')) 

        sensor_data = get_sensor_data_between_timestamps(start, end)
        headers = ['timestamp', 'pressure', 'humidity', 'ambient_light', 'air_quality_index', 'TVOC', 'eCO2']
        return jsonify({'headers': headers, 'data': sensor_data} ), 200
    elif request.method == 'POST':
        data = request.json

        # Parse the incoming JSON data
        if 'timestamp' in data:
            timestamp = datetime.strptime(data['timestamp'], '%Y-%m-%dT%H:%M:%S.%fZ')
        else:
            timestamp = datetime.now()
        try:
            pressure = data['pressure']
            humidity = data['humidity']
            ambient_light = data['ambient_light']
            air_quality_index = data['air_quality_index']
            TVOC = data['TVOC']
            eCO2 = data['eCO2']
        except KeyError as e:
            return jsonify({'success': False, 'error': f"value not provided: {e}"}), 400



        insert_sensor_data(timestamp, pressure, humidity, ambient_light, air_quality_index, TVOC, eCO2)

        return jsonify({'success': True}), 201
