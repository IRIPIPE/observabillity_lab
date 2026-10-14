FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt constraints.txt ./

RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt  

RUN groupadd --gid 10001 appuser \
    && useradd --uid 10001 --gid appuser --create-home appuser

COPY app ./app

USER appuser

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
