FROM python:3.12

WORKDIR /app

RUN pip install uv

COPY pyproject.toml .
RUN uv sync --no-dev

# Install Chromium and its system dependencies
RUN uv run playwright install chromium --with-deps

COPY . .

CMD ["uv", "run", "scrape"]
