from datetime import datetime
import sys
from typing import Dict, List, Optional
from flask import g
from app.extensions import db, psycop_conn, get_real_ip
from zoneinfo import ZoneInfo
from sqlalchemy import func

class FrontendLog(db.Model):
    __tablename__ = 'frontend_logs'
    timestamp = db.Column(db.TIMESTAMP(timezone=True), default=datetime.now(tz=ZoneInfo("UTC")), primary_key=True)
    user_id = db.Column(db.Text)
    user_ip = db.Column(db.Text)
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
        func.count(func.distinct(FrontendLog.user_id)).label('unique_user_id_count'),
        func.count(func.distinct(FrontendLog.user_ip)).label('unique_user_ip_count'),
        func.array_agg(func.distinct(FrontendLog.route)).label('routes')
    ).group_by('bucket').order_by('bucket')

    # Add route filter if specified
    if route:
        if route == '/':
            # Special case for the home route we only want that because by default we get all routes anyway
            query = query.filter(FrontendLog.route == route)
        else:
            query = query.filter(FrontendLog.route.like(f"{route}%"))
    
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
            "unique_user_ids": unique_user_id_count,
            "unique_users_ips": unique_user_ip_count,
            "unique_routes": routes,
        }
        for bucket, total_count, unique_user_id_count, unique_user_ip_count, routes in results
    ]

    # Query to get all unique routes within the time range
    unique_routes_query = db.session.query(
        func.distinct(FrontendLog.route)
    )
    if start_time:
        unique_routes_query = unique_routes_query.filter(FrontendLog.timestamp >= start_time)
    if end_time:
        unique_routes_query = unique_routes_query.filter(FrontendLog.timestamp <= end_time)
    if route:
        if route == '/':
            # Special case for the home route we only want that because by default we get all routes anyway
            unique_routes_query = unique_routes_query.filter(FrontendLog.route == route)
        else:
            unique_routes_query = unique_routes_query.filter(FrontendLog.route.like(f"{route}%"))
    
    unique_routes = [route[0] for route in unique_routes_query.all()]
    
    return data, unique_routes

def insert_frontend_log(route: str):
    timestamp = datetime.now(ZoneInfo("UTC"))
    user_id = g.user_id
    user_ip = get_real_ip()

    log_entry = FrontendLog(user_id=user_id, user_ip=user_ip, route=route, timestamp=timestamp)
    db.session.add(log_entry)
    db.session.commit()