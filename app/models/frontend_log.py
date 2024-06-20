from datetime import datetime
from typing import Dict, List, Optional
from flask import g
from app.extensions import db, psycop_conn
from zoneinfo import ZoneInfo
from sqlalchemy import func

class FrontendLog(db.Model):
    __tablename__ = 'frontend_logs'
    timestamp = db.Column(db.TIMESTAMP(timezone=True), default=datetime.now(tz=ZoneInfo("UTC")), primary_key=True)
    user_id = db.Column(db.Text)
    route = db.Column(db.Text)

def setup_frontend_logs_table():
    conn = psycop_conn()
    cur = conn.cursor()

    # Convert the table to a hypertable if it is not already one
    create_hypertable_query = """
    SELECT create_hypertable('frontend_logs', 'timestamp', if_not_exists => TRUE);
    """
    cur.execute(create_hypertable_query)

    # Commit the changes and close the connection
    conn.commit()
    cur.close()
    conn.close()

def get_frontend_log_per_bucket(
    bucket_size: str = '1 hour', 
    route: Optional[str] = None, 
    start_time: Optional[datetime] = None, 
    end_time: Optional[datetime] = None
) -> List[Dict[str, any]]:
    # Construct the base query with time_bucket
    query = db.session.query(
        func.time_bucket(bucket_size, FrontendLog.timestamp).label('bucket'),
        func.count(FrontendLog.timestamp).label('total_count'),
        func.count(func.distinct(FrontendLog.user_id)).label('unique_user_count')
    ).group_by('bucket').order_by('bucket')

    # Add endpoint filter if specified
    if route:
        query = query.filter(FrontendLog.endpoint.like(f"{route}%"))
    
    # Add time range filter if specified
    if start_time:
        query = query.filter(FrontendLog.timestamp >= start_time)
    if end_time:
        query = query.filter(FrontendLog.timestamp <= end_time)
    
    # Execute the query and fetch all results
    results = query.all()
    
    # Format the results into a list of dictionaries
    data = [
        {
            "timestamp": bucket.isoformat(),
            "total_visits": total_count,
            "unique_users": unique_user_count
        }
        for bucket, total_count, unique_user_count in results
    ]
    
    return data

def insert_frontend_log(route: str):
    timestamp = datetime.now(ZoneInfo("UTC"))
    user_id = g.user_id

    log_entry = FrontendLog(user_id=user_id, route=route, timestamp=timestamp)
    db.session.add(log_entry)
    db.session.commit()