FROM python:3.11-slim

WORKDIR /app
RUN apt-get update && apt-get install -y git curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    google-api-python-client google-auth google-auth-oauthlib \
    google-auth-httplib2 beautifulsoup4 lxml python-docx openpyxl pandas pillow markdown

COPY . .

EXPOSE 8000
CMD ["python3", "gateway.py"]
