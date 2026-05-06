# Aerospace CNC Simulator — publishes telemetry to AWS IoT Core MQTT.
FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
        "numpy>=1.26.0" \
        "awsiotsdk>=1.21.0" \
        "awscrt>=0.20.0"

COPY scripts/simulate_aerospace_cnc.py /app/simulate.py

# Mount IoT certificates as a volume at /app/certs
ENTRYPOINT ["python", "simulate.py"]
CMD ["--mode", "optimal", "--duration", "60"]
