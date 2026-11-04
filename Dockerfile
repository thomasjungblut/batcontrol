# batcontrol on Debian slim. Every dependency ships a manylinux wheel, so
# nothing is compiled and no build tools end up in the image.

# Stage 1: install the package into a virtualenv
FROM python:3.14-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

WORKDIR /build
COPY pyproject.toml LICENSE README.md ./
COPY src ./src
RUN pip install .


# Stage 2: runtime
FROM python:3.14-slim

ARG VERSION=dev
ARG GIT_SHA=unknown
LABEL org.opencontainers.image.title="batcontrol" \
      org.opencontainers.image.description="Simple battery rules for Fronius GEN24 and Tibber" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${GIT_SHA}"

# tzdata: log timestamps follow TZ (set it in compose, e.g. Europe/Berlin).
RUN export DEBIAN_FRONTEND=noninteractive \
    && apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    TZ=UTC \
    BATCONTROL_VERSION=${VERSION} \
    BATCONTROL_GIT_SHA=${GIT_SHA}

WORKDIR /app
# config/ holds batcontrol_config.yaml and the Fronius settings backup that
# is restored on shutdown, so it has to be a volume.
COPY config/batcontrol_config_dummy.yaml /app/config_template/
COPY entrypoint.sh /app/
RUN mkdir -p /app/config /app/logs
VOLUME ["/app/config", "/app/logs"]

# Dashboard and API, when api.enabled is set and api.host is 0.0.0.0.
EXPOSE 8080

# exec in the entrypoint makes python PID 1, so SIGTERM from "docker stop"
# reaches batcontrol and it restores the inverter settings before exiting.
ENTRYPOINT ["/bin/sh", "/app/entrypoint.sh"]
