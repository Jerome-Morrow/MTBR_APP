FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .

# Увеличиваем таймауты и число попыток pip — это спасает при нестабильном интернете
RUN pip install --upgrade pip && \
    pip install --no-cache-dir --retries 5 --timeout 60 -r requirements.txt

COPY . .
EXPOSE 8501
CMD ["streamlit", "run", "main.py", "--server.port=8501", "--server.address=0.0.0.0"]
