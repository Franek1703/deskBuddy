FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY deskbuddy_gateway ./deskbuddy_gateway
# The collector runs on the host (it needs the logged-in Codex / Claude CLIs); the container only serves.
USER 65534:65534
EXPOSE 8443
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD ["python", "-m", "deskbuddy_gateway.healthcheck"]
CMD ["python", "-m", "deskbuddy_gateway.server"]
