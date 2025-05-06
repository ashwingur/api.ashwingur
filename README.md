# api.ashwingur

Using Flask and PostgreSQL (with TimescaleDB extension) in a Docker container

## Startup

One step:

```
docker-compose up --build
```

1. Start the database

```
docker compose up -d flask_db
```

2. Start redis

```
docker compose up -d flask_redis
```

3. Start imgproxy

```
docker compose up -d imgproxy
```

4. Start the flask app

```
docker compose up --build flask_app
```

## .env file

This is required and should be manually created in the root folder

```
# Postgres credentials
POSTGRES_USER=
POSTGRES_PASSWORD=
POSTGRES_DB=

# Other tokens used by Flask
FLASK_ENV=DEV|PROD
FLASK_SECRET_KEY=
WEATHER_POST_PASSWORD=
PARKING_POST_PASSWORD=
OPEN_DATA_TOKEN=

IMGPROXY_KEY=
IMGPROXY_SALT=

# For flask migrate
FLASK_APP="app:create_app"
REDIS_URL=redis://localhost:6379/0

DISCORD_BOT_TOKEN=
```
