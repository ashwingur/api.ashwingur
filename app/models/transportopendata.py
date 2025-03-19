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

    def __repr__(self):
        return f"<ParkingLot(parking_id={self.facility_id}, name={self.name})>"

class ParkingData(db.Model):
    __tablename__ = 'parking_data'
    
    timestamp = db.Column(db.DateTime(timezone=True),
                          primary_key=True, nullable=False, default=datetime.now(tz=ZoneInfo("UTC")))
    facility_id = db.Column(db.Integer, db.ForeignKey('parking_lots.facility_id'), nullable=False)
    spots = db.Column(db.Integer, nullable=False)
    total = db.Column(db.Integer, nullable=False)
    message_date = db.Column(db.DateTime(timezone=True), nullable=False)

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

    # Commit the changes and close the connection
    conn.commit()
    cur.close()
    conn.close()

def query_parking_data(facility_id: int, start_time: datetime, end_time: datetime, bucket_size: str = '1 hour'):
    query = """
    SELECT
        time_bucket(%s, timestamp) AS bucket,
        ROUND(AVG(spots)::numeric, 3)::float AS avg_spots,
        ROUND(AVG(total)::numeric, 3)::float AS avg_total
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
    cur.execute(query, (bucket_size, facility_id, start_time, end_time))
    results = cur.fetchall()
    cur.close()
    conn.close()

    # Format the results as a list of dictionaries
    formatted_results = [
        {
            "time": bucket.isoformat(),  # Convert datetime to string
            "spots": avg_spots,
            "occupied": avg_total
        }
        for bucket, avg_spots, avg_total in results
    ]

    # print(json.dumps(formatted_results, indent=2), file=sys.stderr)  # Debugging output

    return formatted_results



class ParkingLotSchema(SQLAlchemyAutoSchema):
    parking_id = fields.Int(required=True)
    name = fields.Str(required=True)

class ParkingDataSchema(SQLAlchemyAutoSchema):
    timestamp = fields.DateTime(required=True)
    facility_id = fields.Int(required=True)
    spots = fields.Int(required=True)
    total = fields.Int(required=True)
    message_date = fields.DateTime(required=True)