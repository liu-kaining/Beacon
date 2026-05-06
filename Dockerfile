FROM python:3.11-slim

# Install uv
RUN pip install --no-cache-dir uv

WORKDIR /app

# Copy project files
COPY pyproject.toml uv.lock ./
COPY src/ src/
COPY templates/ templates/

# Install dependencies
RUN uv sync --frozen --no-dev

# Create directories (data/ and docs/ are mounted as volumes in CI)
RUN mkdir -p data docs

CMD ["uv", "run", "python", "src/main.py"]
