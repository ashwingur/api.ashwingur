from datetime import datetime
import sys
from typing import Dict, List, Optional
from flask import g
from app.extensions import db, psycop_conn, get_real_ip
from zoneinfo import ZoneInfo
from sqlalchemy import func, text

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
    # Construct the base query with time_bucket_gapfill
    # Using a custom query because sqlalchemy doesnt support time_bucket_gapfill
    base_query = """
        SELECT 
            time_bucket_gapfill(:bucket_size, timestamp) AS bucket,
            COALESCE(count(timestamp), 0) AS total_count,
            COALESCE(count(DISTINCT user_id), 0) AS unique_user_id_count,
            COALESCE(count(DISTINCT user_ip), 0) AS unique_user_ip_count,
            COALESCE(array_agg(DISTINCT route), ARRAY[]::varchar[]) AS routes
        FROM frontend_logs
        WHERE (:start_time IS NULL OR timestamp >= :start_time)
          AND (:end_time IS NULL OR timestamp <= :end_time)
          {route_filter}
        GROUP BY bucket
        ORDER BY bucket;
    """
    
    # Construct the route filter if needed
    route_filter = ""
    if route:
        if route == '/':
            route_filter = "AND route = '/'"
        else:
            route_filter = "AND route LIKE :route"

    # Add the route filter to the base query
    base_query = base_query.format(route_filter=route_filter)

    # Execute the raw SQL with parameters
    result = db.session.execute(
        text(base_query), 
        {
            'bucket_size': bucket_size, 
            'start_time': start_time, 
            'end_time': end_time, 
            'route': f"{route}%" if route and route != '/' else route
        }
    )

    # Fetch all results
    rows = result.fetchall()
    
    # Format the results into a list of dictionaries
    data = [
        {
            "timestamp": row.bucket.isoformat(),
            "total_visits": row.total_count,
            "unique_user_ids": row.unique_user_id_count,
            "unique_users_ips": row.unique_user_ip_count,
            "unique_routes": row.routes,
        }
        for row in rows
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
    
    # Query to get total unique user ids and ips for the entire period
    total_unique_query = db.session.query(
        func.count().label('total_count'),
        func.count(func.distinct(FrontendLog.user_id)).label('total_unique_user_id_count'),
        func.count(func.distinct(FrontendLog.user_ip)).label('total_unique_user_ip_count')
    )
    if start_time:
        total_unique_query = total_unique_query.filter(FrontendLog.timestamp >= start_time)
    if end_time:
        total_unique_query = total_unique_query.filter(FrontendLog.timestamp <= end_time)
    if route:
        if route == '/':
            total_unique_query = total_unique_query.filter(FrontendLog.route == route)
        else:
            total_unique_query = total_unique_query.filter(FrontendLog.route.like(f"{route}%"))

    total_unique_result = total_unique_query.one()
    total_count = total_unique_result.total_count
    total_unique_user_id_count = total_unique_result.total_unique_user_id_count
    total_unique_user_ip_count = total_unique_result.total_unique_user_ip_count

    # Return the data with the additional total unique counts
    return {
        "timeseries_data": data,
        "unique_routes": unique_routes,
        "total_count": total_count,
        "total_unique_user_id_count": total_unique_user_id_count,
        "total_unique_user_ip_count": total_unique_user_ip_count
    }

def insert_frontend_log(route: str):
    timestamp = datetime.now(ZoneInfo("UTC"))
    user_id = g.user_id
    user_ip = get_real_ip()

    log_entry = FrontendLog(user_id=user_id, user_ip=user_ip, route=route, timestamp=timestamp)
    db.session.add(log_entry)
    db.session.commit()