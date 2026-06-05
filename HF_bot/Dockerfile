FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=7860 \
    DATA_DIR=/data

WORKDIR /app
RUN pip install --no-cache-dir flask gunicorn
COPY Analyzer_bot.py /app/Analyzer_bot.py
RUN mkdir -p /data
EXPOSE 7860
CMD ["gunicorn", "--bind", "0.0.0.0:7860", "Analyzer_bot:app"]
