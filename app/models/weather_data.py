from datetime import datetime, timedelta
import random
from app.extensions import psycop_conn
from psycopg2 import sql

# Create the sensor data table and convert it to a hypertable
def setup_sensor_data_table():
    conn = psycop_conn()
    cur = conn.cursor()

    # Create the data table if it does not exist
    # create sensor data hypertable
    query_create_sensordata_table = """
    CREATE TABLE IF NOT EXISTS sensor_data (
        timestamp TIMESTAMPTZ NOT NULL,
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

def insert_sensor_data(timestamp, pressure, humidity, ambient_light, air_quality_index, TVOC, eCO2):
    """
    Insert a new record into the sensor_data table.
    """
    insert_query = """
    INSERT INTO sensor_data (timestamp, pressure, humidity, ambient_light, air_quality_index, TVOC, eCO2)
    VALUES (%s, %s, %s, %s, %s, %s, %s);
    """
    # Connect to the database and execute the insert query
    conn = psycop_conn()
    with conn:
        with conn.cursor() as cur:
            cur.execute(insert_query, (timestamp, pressure, humidity, ambient_light, air_quality_index, TVOC, eCO2))
    conn.close()

def get_all_sensor_data():
    """
    Fetch all sensor data from the database, sorted by timestamp.
    """
    conn = psycop_conn()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT timestamp, pressure, humidity, ambient_light, air_quality_index, TVOC, eCO2
            FROM sensor_data
            ORDER BY timestamp
        """)
        rows = cur.fetchall()
    conn.close()

    sensor_data_list = [[int(row[0].timestamp()), row[1], row[2], row[3], row[4], row[5], row[6]] for row in rows]

    return sensor_data_list

def test_insert_sensor_data(n, time_gap_seconds=300):
    """
    Insert 'n' rows into the sensor_data table with timestamps incremented by 'time_gap' seconds.
    """
    # Current timestamp
    current_timestamp = datetime.now()
    
    for i in range(n):
        # Generate reasonable random values for other columns
        pressure = random.uniform(950, 1050)  # Assuming pressure in hPa
        humidity = random.uniform(30, 90)     # Assuming humidity in %
        ambient_light = random.uniform(0, 1000) # Assuming ambient light in lux
        air_quality_index = random.randint(1, 5) # Assuming AQI index
        TVOC = random.uniform(0, 600)         # Total Volatile Organic Compounds in ppb
        eCO2 = random.uniform(400, 5000)      # Equivalent CO2 in ppm
        
        # Call the insert function
        insert_sensor_data(
            current_timestamp,
            pressure,
            humidity,
            ambient_light,
            air_quality_index,
            TVOC,
            eCO2
        )
        
        # Increment the timestamp by 'time_gap' seconds
        current_timestamp += timedelta(seconds=time_gap_seconds)
