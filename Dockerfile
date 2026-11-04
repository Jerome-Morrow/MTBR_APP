FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .

# Системные зависимости для WeasyPrint (Pango/Cairo) + шрифты с кириллицей
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libharfbuzz-subset0 \
    fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

# Увеличиваем таймауты и число попыток pip — это спасает при нестабильном интернете
RUN pip install --upgrade pip && \
    pip install --no-cache-dir --retries 5 --timeout 60 -r requirements.txt

COPY . .
EXPOSE 8501
CMD ["streamlit", "run", "main.py", "--server.port=8501", "--server.address=0.0.0.0"]
