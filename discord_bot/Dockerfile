FROM python:3.10-slim-buster

WORKDIR /bot

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

CMD ["python", "bot.py"]
