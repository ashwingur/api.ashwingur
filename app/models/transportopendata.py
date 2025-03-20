from datetime import datetime
import sys
from marshmallow import fields
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema
from app.extensions import db, psycop_conn
from zoneinfo import ZoneInfo


class ParkingLot(db.Model):
    __tablename__ = 'parking_lots'
    
    facility_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    capacity = db.Column(db.Integer, nullable=False)
    occupancy = db.Column(db.Integer, nullable=False)

    def to_dict(self):
        return {
            "facility_id": self.facility_id,
            "name": self.name,
            "capacity": self.capacity,
            "occupancy": self.occupancy
        }

    def __repr__(self):
        return f"<ParkingLot(parking_id={self.facility_id}, name={self.name})>"

class ParkingData(db.Model):
    __tablename__ = 'parking_data'
    
    timestamp = db.Column(db.DateTime(timezone=True),
                          primary_key=True, nullable=False, default=datetime.now(tz=ZoneInfo("UTC")))
    facility_id = db.Column(db.Integer, db.ForeignKey('parking_lots.facility_id'), nullable=False)
    occupancy = db.Column(db.Integer, nullable=False)

    # Relationship to the existing ParkingLot model
    facility = db.relationship('ParkingLot', backref=db.backref('parking_data', lazy=True))

    def __repr__(self):
        return f'<ParkingData {self.facility_id} - {self.spots} spots>'

def set_parking_data_table():
    conn = psycop_conn()
    cur = conn.cursor()

    # Convert the table to a hypertable if it is not already one
    create_hypertable_query = """
    SELECT create_hypertable('parking_data', 'timestamp', if_not_exists => TRUE);
    """
    cur.execute(create_hypertable_query)

    # Create index if it doesn't exist
    index_creation_query = """
        CREATE INDEX IF NOT EXISTS idx_parking_data_facility_id_timestamp 
        ON parking_data (facility_id, timestamp DESC);
    """
    cur.execute(index_creation_query)   

    # Commit the changes and close the connection
    conn.commit()
    cur.close()
    conn.close()

def query_parking_data(facility_id: int, start_time: datetime, end_time: datetime, bucket_size: str|None = None):
    if bucket_size is None:
        days = (end_time - start_time).days
        if days <= 2:
            time_bucket = '5 minutes'
        elif days <= 4:
            time_bucket = '15 minutes'
        elif days <= 7:
            time_bucket = '30 minutes'
        elif days <= 14:
            time_bucket = '1 hour'
        elif days <= 32:
            time_bucket = '2 hours'
        elif days <= 90:
            time_bucket = '1 day'
        else:
            time_bucket = '7 days'
    else:
        time_bucket = bucket_size


    query = """
    SELECT
        time_bucket(%s, timestamp) AS bucket,
        ROUND(AVG(occupancy))::INTEGER AS occupancy
    FROM
        parking_data
    WHERE
        facility_id = %s
        AND timestamp >= %s AND timestamp <= %s
    GROUP BY
        bucket
    ORDER BY
        bucket;
    """

    conn = psycop_conn()
    cur = conn.cursor()
    cur.execute(query, (time_bucket, facility_id, start_time, end_time))
    results = cur.fetchall()
    cur.close()
    conn.close()

    # Format the results as a list of dictionaries
    formatted_results = [
        {
            "time": bucket.isoformat(),  # Convert datetime to string
            "occupied": occupancy
        }
        for bucket, occupancy in results
    ]

    return formatted_results

def query_min_and_max_parking(facility_id: int, start_time: datetime, end_time: datetime):
    # Query for global min and max occupancy over the entire time range
    query = """
    SELECT
        MIN(occupancy) AS min_occupancy,
        MAX(occupancy) AS max_occupancy
    FROM
        parking_data
    WHERE
        facility_id = %s
        AND timestamp >= %s AND timestamp <= %s;
    """

    # Run the global min/max query
    conn = psycop_conn()
    cur = conn.cursor()
    cur.execute(query, (facility_id, start_time, end_time))
    min_max_result = cur.fetchone()
    min_occupancy = min_max_result[0]
    max_occupancy = min_max_result[1]

    return (min_occupancy, max_occupancy)



class ParkingLotSchema(SQLAlchemyAutoSchema):
    parking_id = fields.Int(required=True)
    name = fields.Str(required=True)

class ParkingDataSchema(SQLAlchemyAutoSchema):
    timestamp = fields.DateTime(required=True)
    facility_id = fields.Int(required=True)
    spots = fields.Int(required=True)
    total = fields.Int(required=True)
    message_date = fields.DateTime(required=True)