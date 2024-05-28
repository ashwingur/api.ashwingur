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
