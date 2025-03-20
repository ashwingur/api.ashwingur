from datetime import datetime
import sys
from typing import List
from flask import jsonify, request
import requests
from app.models.transportopendata import ParkingData, ParkingLot, query_parking_data
from app.transportopendata import bp
from app.extensions import db, roles_required, limiter
from config import Config
from zoneinfo import ZoneInfo
from app.analytics.routes import parse_datetime

API_KEY = f"apikey {Config.OPEN_DATA_TOKEN}"
BASE_URL = "https://api.transport.nsw.gov.au/v1/carpark"
headers = {
    "Authorization": API_KEY,
}

@bp.route('set_parking_lots', methods=['POST'])
@limiter.limit('4/minute', override_defaults=True)
def set_parking_lots():
    '''
    Calls the baseurl of the parking API to get a list of parking lots and updates the table accordingly
    '''    
    response = requests.get(BASE_URL, headers=headers)
    if response.status_code == 200:
        data = response.json()
        for facility_id, name in data.items():
            # Skip IDs 5 and lower because they are historical only
            if int(facility_id) <= 5:
                continue
            
            # Query for to get the latest capacity and spots
            parking_data_response = requests.get(f"{BASE_URL}?facility={facility_id}", headers=headers)
            if parking_data_response.status_code != 200:
                 continue
            
            parking_data = parking_data_response.json()
            
            occupancy = parking_data["occupancy"]["total"]
            capacity = parking_data["spots"]

            # Check if the parking lot exists
            parking_lot = db.session.query(ParkingLot).filter_by(facility_id=facility_id).first()
            if parking_lot:
                parking_lot.name = name
                parking_lot.occupancy = occupancy
                parking_lot.capacity = capacity
            else:
                parking_lot = ParkingLot(facility_id=int(facility_id), name=name, occupancy=occupancy, capacity=capacity)
                db.session.add(parking_lot)
            db.session.commit()
        return jsonify(response.json())  # Return the JSON response
    else:
        return jsonify({"error": f"Request failed with status {response.status_code}", "details": response.text}), response.status_code
    
@bp.route('parking_data', methods=['POST'])
@limiter.limit('10/minute', override_defaults=True)
def post_parking_data():
    parking_lots: List[ParkingLot] = ParkingLot.query.all()
    post_body = request.json

    if 'password' not in post_body:
            return jsonify({"success": False, 'error': 'password not provided'}), 400
    if post_body['password'] != Config.PARKING_POST_PASSWORD:
            return jsonify({"success": False, 'error': 'incorrect password'}), 400

    for parking_lot in parking_lots:
        response = requests.get(f"{BASE_URL}?facility={parking_lot.facility_id}", headers=headers)
        if response.status_code != 200:
            continue
        data = response.json()
        timestamp = datetime.now(ZoneInfo("UTC"))
        facility_id = data["facility_id"]  
        occupancy = data["occupancy"]["total"]
        parking_data = ParkingData(timestamp=timestamp, facility_id=facility_id, occupancy=occupancy)
        db.session.add(parking_data)
        db.session.commit()
    
    return jsonify({"success": True}), 201


@bp.route('parking_data/<int:facility_id>', methods=['GET'])
@limiter.limit('30/minute', override_defaults=True)
def get_parking_data(facility_id):
    start = request.args.get('start_time')
    end = request.args.get('end_time')

    # Validate input parameters
    if not start or not end:
        return jsonify({"success": False, "error": "'start_time' and 'end_time' must be provided"}), 400

    start_time = parse_datetime(start)
    end_time = parse_datetime(end)

    # Check if facility_id exists in ParkingLot table
    facility = db.session.query(ParkingLot).filter_by(facility_id=facility_id).first()
    if not facility:
        return jsonify({"success": False, "error": "Facility ID not found"}), 404

    # Query parking data
    data = query_parking_data(facility_id, start_time=start_time, end_time=end_time)

    # Format response
    response = {
        "facility_id": facility_id,
        "facility_name": facility.name,
        "capacity": facility.capacity,
        "parking_data": data
    }

    return jsonify(response), 200
