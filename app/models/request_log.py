from datetime import datetime
from typing import Dict, List, Optional
from app.extensions import db, psycop_conn
from zoneinfo import ZoneInfo
from sqlalchemy import func, text

class RequestLog(db.Model):
    __tablename__ = 'request_logs'
    timestamp = db.Column(db.TIMESTAMP(timezone=True), default=datetime.now(tz=ZoneInfo("UTC")), primary_key=True)
    user_id = db.Column(db.Text)
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

def get_api_requests_per_bucket(
    bucket_size: str = '1 hour', 
    endpoint: Optional[str] = None, 
    start_time: Optional[datetime] = None, 
    end_time: Optional[datetime] = None
) -> List[Dict[str, any]]:
    # Construct the base query with time_bucket_gapfill
    base_query = """
        SELECT 
            time_bucket_gapfill(:bucket_size, timestamp) AS bucket,
            COALESCE(count(timestamp), 0) AS total_count,
            COALESCE(count(DISTINCT user_id), 0) AS unique_user_id_count,
            COALESCE(count(DISTINCT user_ip), 0) AS unique_user_ip_count,
            COALESCE(array_agg(DISTINCT endpoint), ARRAY[]::varchar[]) AS endpoints
        FROM request_logs
        WHERE (:start_time IS NULL OR timestamp >= :start_time)
          AND (:end_time IS NULL OR timestamp <= :end_time)
          {endpoint_filter}
        GROUP BY bucket
        ORDER BY bucket;
    """
    
    # Construct the endpoint filter if needed
    endpoint_filter = ""
    if endpoint:
        endpoint_filter = "AND endpoint LIKE :endpoint"

    # Add the endpoint filter to the base query
    base_query = base_query.format(endpoint_filter=endpoint_filter)

    # Execute the raw SQL with parameters
    result = db.session.execute(
        text(base_query), 
        {
            'bucket_size': bucket_size, 
            'start_time': start_time, 
            'end_time': end_time, 
            'endpoint': f"{endpoint}%" if endpoint else None
        }
    )

    # Fetch all results
    rows = result.fetchall()

    # Format the results into a list of dictionaries
    time_data = [
        {
            "timestamp": row.bucket.isoformat(),
            "total_requests": row.total_count,
            "unique_user_ids": row.unique_user_id_count,
            "unique_user_ips": row.unique_user_ip_count,
            "unique_endpoints": row.endpoints
        }
        for row in rows
    ]

    # Query to get all unique endpoints within the time range
    unique_endpoints_query = db.session.query(
        func.distinct(RequestLog.endpoint)
    )
    if start_time:
        unique_endpoints_query = unique_endpoints_query.filter(RequestLog.timestamp >= start_time)
    if end_time:
        unique_endpoints_query = unique_endpoints_query.filter(RequestLog.timestamp <= end_time)
    if endpoint:
        unique_endpoints_query = unique_endpoints_query.filter(RequestLog.endpoint.like(f"{endpoint}%"))
    
    unique_endpoints = [ep[0] for ep in unique_endpoints_query.all()]

    # Query to get total unique user ids and ips for the entire period
    total_unique_query = db.session.query(
        func.count().label('total_count'),
        func.count(func.distinct(RequestLog.user_id)).label('total_unique_user_id_count'),
        func.count(func.distinct(RequestLog.user_ip)).label('total_unique_user_ip_count')
    )
    if start_time:
        total_unique_query = total_unique_query.filter(RequestLog.timestamp >= start_time)
    if end_time:
        total_unique_query = total_unique_query.filter(RequestLog.timestamp <= end_time)
    if endpoint:
        total_unique_query = total_unique_query.filter(RequestLog.endpoint.like(f"{endpoint}%"))

    total_unique_result = total_unique_query.one()
    total_count = total_unique_result.total_count
    total_unique_user_id_count = total_unique_result.total_unique_user_id_count
    total_unique_user_ip_count = total_unique_result.total_unique_user_ip_count

    # Return the data with the additional total unique counts
    return {
        "timeseries_data": time_data,
        "unique_endpoints": unique_endpoints,
        "total_count": total_count,
        "total_unique_user_id_count": total_unique_user_id_count,
        "total_unique_user_ip_count": total_unique_user_ip_count
    }




