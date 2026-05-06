# Quality Vision Manager — YOLOv8 + Rekognition fallback (<3s SLA).
FROM factorymind/base:latest

# Pillow + opencv-headless for image preprocessing
RUN pip install --no-cache-dir \
        "pillow>=10.0.0" \
        "opencv-python-headless>=4.9.0"

CMD ["quality_vision.manager.handler.handler"]
