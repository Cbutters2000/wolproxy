# Use a slim version of Python to keep the image size small! 📦️💨️
FROM python:3.11-slim

WORKDIR /app

# Copy our files in
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# Run the app on port 80
CMD ["python", "main.py"]
