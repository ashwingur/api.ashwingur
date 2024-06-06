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

1. Start redis

```
docker compose up -d flask_redis
```

3. Start the flask app

```
docker compose up --build flask_app
```

## .env file

This is required and should be manually created in the root folder

```
POSTGRES_USER=abc
POSTGRES_PASSWORD=def
POSTGRES_DB=ghi
FLASK_SECRET_KEY=jkl
WEATHER_POST_PASSWORD=xyz
```
