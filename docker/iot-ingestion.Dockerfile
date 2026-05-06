# IoT Ingestion Manager — Kinesis batch processor (<500ms SLA).
FROM factorymind/base:latest
CMD ["iot_ingestion.manager.handler.handler"]
