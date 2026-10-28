FROM python:3.12-slim

# Don't write .pyc files into the bind mount; flush stdout immediately so logs appear in `docker logs`.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install dependencies before copying source, so code edits don't invalidate this cached layer.
ARG REQUIREMENTS=requirements/prod.txt
COPY requirements/ requirements/
RUN pip install -r ${REQUIREMENTS}

# Never run the app as root inside the container.
RUN useradd --create-home --uid 1000 appuser
COPY --chown=appuser:appuser . .
USER appuser

EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
