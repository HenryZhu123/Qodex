FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md alembic.ini ./
COPY migrations ./migrations
COPY prompts ./prompts
COPY src ./src

RUN pip install --no-cache-dir .

ENTRYPOINT ["alembic", "upgrade", "head"]
