FROM python:3.10-slim-buster

WORKDIR /app

COPY requirements.txt ./

RUN pip install -r requirements.txt

COPY . .

EXPOSE 5000

ENV FLASK_ENV=development

CMD ["gunicorn", "-w", "5", "-b", "0.0.0.0:5000", "--worker-class", "eventlet", "app:create_app()"]
