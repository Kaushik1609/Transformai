# =============================================================================
# KaryaSetu AI — Hardened Agent Sandbox Dockerfile
# Theme: Blockchain & CyberSecurity (SIH 26154)
# =============================================================================
FROM python:3.11-alpine

# Security: Create non-root user and group
RUN addgroup -g 1000 sandboxgroup && \
    adduser -u 1000 -G sandboxgroup -s /bin/sh -D sandboxuser

WORKDIR /app

# Copy the sandbox in-container runner
COPY backend/app/sandbox/entrypoint.py /app/entrypoint.py

# Set strict permissions
RUN chown -R sandboxuser:sandboxgroup /app && \
    chmod 555 /app/entrypoint.py

# Switch to non-root user
USER 1000:1000

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "/app/entrypoint.py"]
