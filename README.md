# api.ashwingur

Using Flask and PostgreSQL (with TimescaleDB extension) in a Docker container

## Startup

1. Start the database

```
docker compose up -d flask_db
```

2. Start the flask app

```
docker compose up --build flask_app
```

## .env file

This is required and should be manually created in the base folder

```
POSTGRES_USER=abc
POSTGRES_PASSWORD=def
POSTGRES_DB=ghi
FLASK_SECRET_KEY=jkl
```
