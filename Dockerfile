FROM python:3.10-slim-buster

# Install Ghostscript (for EPS file conversions)
RUN apt-get update && apt-get install -y ghostscript

WORKDIR /app

COPY requirements.txt ./

RUN pip install -r requirements.txt

COPY . .

RUN mkdir -p /app/static/images

EXPOSE 5000

ENV FLASK_ENV=development

# Only 1 worker thread, otherwise flask socket messes up
CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:5000", "--worker-class", "eventlet", "app:create_app()"]
