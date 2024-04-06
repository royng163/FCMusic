# syntax=docker/dockerfile:1

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN adduser --disabled-password --gecos "" --home "/nonexistent" --shell "/sbin/nologin" --no-create-home --uid 10001 appuser

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip python -m pip install -r requirements.txt

COPY . .

EXPOSE 8000

CMD cd /app
