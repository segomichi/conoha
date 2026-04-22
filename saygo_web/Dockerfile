FROM python:3.12-slim

WORKDIR /saygo_web
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
COPY . /saygo_web/
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py collectstatic --noinput && gunicorn saygo_web.wsgi:application --bind 0.0.0.0:8000"]
