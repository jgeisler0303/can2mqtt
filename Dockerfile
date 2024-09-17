FROM python:3.10-slim-buster

WORKDIR /app

COPY requirement.txt requirement.txt
RUN pip3 install -r requirement.txt
COPY . .

CMD ["python3", "can2mqtt.py"]
