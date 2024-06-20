from datetime import datetime
from app.extensions import db, psycop_conn
from zoneinfo import ZoneInfo
from sqlalchemy import func

class RequestLog(db.Model):
    __tablename__ = 'request_logs'
    # id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.TIMESTAMP(timezone=True), default=datetime.now(tz=ZoneInfo("UTC")), primary_key=True)
    user_ip = db.Column(db.Text)
    endpoint = db.Column(db.Text)
    method = db.Column(db.Text)


def setup_request_logs_table():
    conn = psycop_conn()
    cur = conn.cursor()

    # Convert the table to a hypertable if it is not already one
    create_hypertable_query = """
    SELECT create_hypertable('request_logs', 'timestamp', if_not_exists => TRUE);
    """
    cur.execute(create_hypertable_query)

    # Commit the changes and close the connection
    conn.commit()
    cur.close()
    conn.close()

def get_requests_per_bucket(bucket_size='1 hour', endpoint=None):
    # Construct the base query with time_bucket
    query = db.session.query(
        func.time_bucket(bucket_size, RequestLog.timestamp).label('bucket'),
        func.count(RequestLog.timestamp).label('count')
    ).group_by('bucket').order_by('bucket')

    # Add endpoint filter if specified
    if endpoint:
        query = query.filter(RequestLog.endpoint == endpoint)
    
    # Execute the query and fetch all results
    results = query.all()
    
    return results



