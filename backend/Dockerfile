FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt requirements-test.txt ./
RUN pip install --no-cache-dir -r requirements-test.txt
COPY wallet_lab ./wallet_lab
COPY migrations ./migrations
COPY tests ./tests
