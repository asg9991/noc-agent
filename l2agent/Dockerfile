# Casa 3 en contenedor: solo lo necesario para correr el L2.
# Base alpine porque ya está en el lab (cero pull). Non-root siempre.
FROM python:3.12-alpine

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

RUN adduser -D -u 10001 agente && pip install --no-cache-dir httpx

WORKDIR /app
COPY agent/ ./agent/
COPY mcp/ ./mcp/
COPY l2agent/ ./l2agent/

USER agente
ENTRYPOINT ["python", "-m", "l2agent.main"]
CMD ["--help"]
