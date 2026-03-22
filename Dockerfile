# Stage 1: Build
FROM python:3.12-slim AS builder

WORKDIR /build

COPY pyproject.toml .
COPY src/ src/

RUN pip install --no-cache-dir --prefix=/install .

# Stage 2: Runtime
FROM python:3.12-slim

RUN groupadd -r backuppilot && useradd -r -g backuppilot -s /sbin/nologin backuppilot

COPY --from=builder /install /usr/local

# Install rclone for gdrive checks (optional, lightweight)
RUN apt-get update && apt-get install -y --no-install-recommends \
    rclone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /home/backuppilot
USER backuppilot

# Config and history are expected as volume mounts
VOLUME ["/home/backuppilot/.backuppilot"]

ENTRYPOINT ["backuppilot"]
CMD ["--help"]
