# Digital Twin Manager — Redis + DynamoDB + TwinMaker + AppSync sync (<500ms SLA).
FROM factorymind/base:latest
CMD ["digital_twin.manager.handler.handler"]
