from datetime import datetime, timedelta
import random
from app.extensions import psycop_conn
from psycopg2 import sql
from zoneinfo import ZoneInfo

# Create the sensor data table and convert it to a hypertable
def setup_sensor_data_table():
    conn = psycop_conn()
    cur = conn.cursor()

    # Create the data table if it does not exist
    # create sensor data hypertable
    query_create_sensordata_table = """
    CREATE TABLE IF NOT EXISTS sensor_data (
        timestamp TIMESTAMPTZ NOT NULL,
        temperature FLOAT,
        pressure FLOAT,
        humidity FLOAT,
        ambient_light FLOAT,
        air_quality_index SMALLINT CHECK (air_quality_index >= 1 AND air_quality_index <= 5),
        TVOC SMALLINT,
        eCO2 SMALLINT
    );
    """

    cur.execute(query_create_sensordata_table)

    # Convert the table to a hypertable if it is not already one
    create_hypertable_query = """
    SELECT create_hypertable('sensor_data', 'timestamp', if_not_exists => TRUE);
    """
    cur.execute(create_hypertable_query)

    # Commit the changes and close the connection
    conn.commit()
    cur.close()
    conn.close()

def insert_sensor_data(timestamp, temperature, pressure, humidity, ambient_light, air_quality_index, TVOC, eCO2):
    """
    Insert a new record into the sensor_data table.
    """
    insert_query = """
    INSERT INTO sensor_data (timestamp, temperature, pressure, humidity, ambient_light, air_quality_index, TVOC, eCO2)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
    """
    # Connect to the database and execute the insert query
    conn = psycop_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute(insert_query, (timestamp, temperature, pressure, humidity, ambient_light, air_quality_index, TVOC, eCO2))
    conn.close()

def get_latest_single_sensor_data():
    """
    Fetch the latest sensor data from the database based on the timestamp.
    """
    conn = psycop_conn()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT timestamp, temperature, pressure, humidity, ambient_light, air_quality_index, TVOC, eCO2
            FROM sensor_data
            ORDER BY timestamp DESC
            LIMIT 1
        """)
        row = cur.fetchone()
    conn.close()

    if row:
        latest_data = [int(row[0].timestamp()), row[1], row[2], row[3], row[4], row[5], row[6], row[7]]
        return latest_data
    else:
        return []


def get_all_sensor_data():
    """
    Fetch all sensor data from the database, sorted by timestamp.
    """
    conn = psycop_conn()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT timestamp, temperature, pressure, humidity, ambient_light, air_quality_index, TVOC, eCO2
            FROM sensor_data
            ORDER BY timestamp
        """)
        rows = cur.fetchall()
    conn.close()

    sensor_data_list = [[int(row[0].timestamp()), row[1], row[2], row[3], row[4], row[5], row[6], row[7]] for row in rows]

    return sensor_data_list

def get_sensor_data_between_timestamps(start: datetime, end: datetime, custom_time_bucket=None):
    """
    Retrieve sensor data aggregated over the specified time bucket between start and end timestamps.
    
    Parameters:
    - start: The start timestamp (datetime object).
    - end: The end timestamp (datetime object).
    - custom_time_bucket: Optional. A string representing the time bucket for aggregation (e.g., '1 hour', '1 day', '30 minutes').
    
    Returns:
    - results: A list of lists containing the aggregated data.
    """
    if custom_time_bucket is None:
        days = (end - start).days
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
            time_bucket = '6 hours'
        else:
            time_bucket = '1 day'
    else:
        time_bucket = custom_time_bucket

    query = """
    SELECT
        time_bucket(%s, timestamp) AS bucket,
        ROUND(AVG(temperature)::numeric, 3)::float AS avg_temperature,
        ROUND(AVG(pressure)::numeric, 3)::float AS avg_pressure,
        ROUND(AVG(humidity)::numeric, 3)::float AS avg_humidity,
        ROUND(AVG(ambient_light)::numeric, 3)::float AS avg_ambient_light,
        ROUND(AVG(air_quality_index), 3)::float AS avg_air_quality_index,
        ROUND(AVG(TVOC), 3)::float AS avg_TVOC,
        ROUND(AVG(eCO2), 3)::float AS avg_eCO2
    FROM
        sensor_data
    WHERE
        timestamp >= %s AND timestamp <= %s
    GROUP BY
        bucket
    ORDER BY
        bucket;
    """

    conn = psycop_conn()
    cur = conn.cursor()
    cur.execute(query, (time_bucket, start, end))
    results = cur.fetchall()
    cur.close()
    conn.close()

    return [[int(row[0].timestamp()), row[1], row[2], row[3], row[4], row[5], row[6], row[7]] for row in results]


def execute_sensor_query(query):
    # Check if the query is a read-only query
    if not query.strip().lower().startswith("select"):
        raise ValueError("Only SELECT queries are allowed.")
    
    conn = psycop_conn()
    with conn.cursor() as cur:
        cur.execute(query)
        results = cur.fetchall()
    conn.close()
    results = [[int(row[0].timestamp()), row[1], row[2], row[3], row[4], row[5], row[6], row[7]] for row in results]
    return results

def test_insert_sensor_data(n: int, days_from_past=0, time_gap_seconds=300):
    """
    Insert 'n' rows into the sensor_data table with timestamps incremented by 'time_gap' seconds.

    Parameters:
    - n: Number of rows to add
    - days_from_past: Positive number representing how many days in the past to generate from
    - time_gap_seconds: sampling interval

    """
    # Current timestamp
    current_timestamp = datetime.now(tz=ZoneInfo("UTC")) - timedelta(days=days_from_past)
    
    for i in range(n):
        # Generate reasonable random values for other columns
        temperature = random.uniform(10, 40)  # Celsius
        pressure = random.uniform(950, 1050)  # Assuming pressure in hPa
        humidity = random.uniform(30, 90)     # Assuming humidity in %
        ambient_light = random.uniform(0, 1000) # Assuming ambient light in lux
        air_quality_index = random.randint(1, 5) # Assuming AQI index
        TVOC = random.uniform(0, 600)         # Total Volatile Organic Compounds in ppb
        eCO2 = random.uniform(400, 5000)      # Equivalent CO2 in ppm
        
        # Call the insert function
        insert_sensor_data(
            current_timestamp,
            temperature,
            pressure,
            humidity,
            ambient_light,
            air_quality_index,
            TVOC,
            eCO2
        )
        
        # Increment the timestamp by 'time_gap' seconds
        current_timestamp += timedelta(seconds=time_gap_seconds)
