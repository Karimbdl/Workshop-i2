# Image commune aux microservices Python (FastAPI).
# Contexte de build : ./services — usage : --build-arg SERVICE_DIR=auth-service
FROM python:3.12-slim

ARG SERVICE_DIR
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app
COPY common/requirements.txt /tmp/common-requirements.txt
COPY ${SERVICE_DIR}/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/common-requirements.txt -r /tmp/requirements.txt

COPY common/resilience_common ./resilience_common
COPY ${SERVICE_DIR}/app ./app

# Dossier d'état inscriptible (ex. modèle ML persistant). Inutile mais sans effet pour les autres services.
# Un volume monté ici hérite de cette appartenance, donc l'utilisateur non root peut y écrire.
RUN install -d -o 10001 -g 10001 /app/model

USER 10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-server-header"]
