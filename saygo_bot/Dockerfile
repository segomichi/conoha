FROM python:3.12-slim

WORKDIR /saygo_bot

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY . /saygo_bot/
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

CMD ["python", "saygo_bot.py"]
