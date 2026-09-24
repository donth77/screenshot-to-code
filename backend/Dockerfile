# React Native preview runtime (rn-runtime/, next to backend/). It arrives as
# the named build context "rn-runtime": docker compose passes it (see
# docker-compose.yml); with plain docker build, from the repo root:
#   docker build --build-context rn-runtime=rn-runtime backend
FROM node:22.22.1-bookworm-slim AS rn-runtime-build

RUN npm install -g pnpm@10.32.1

WORKDIR /rn-runtime

COPY --from=rn-runtime package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# Only what the build reads; never a host node_modules (esbuild is per-platform).
COPY --from=rn-runtime build.mjs expo-sdk.json device-profiles.json ./
COPY --from=rn-runtime src ./src
COPY --from=rn-runtime calibration/fit.json ./calibration/
RUN pnpm build

FROM python:3.12.3-slim-bookworm

ENV POETRY_VERSION 1.8.0

# Install system dependencies
RUN pip install "poetry==$POETRY_VERSION"

# Set work directory
WORKDIR /app

# Copy only requirements to cache them in docker layer
COPY poetry.lock pyproject.toml /app/

# Disable the creation of virtual environments
RUN poetry config virtualenvs.create false

# Install dependencies
RUN poetry install

# Install Chromium and Linux libraries needed by Playwright screenshot previews.
RUN playwright install --with-deps chromium

# The built preview runtime, served at /rn-runtime and used for React Native
# screenshots.
COPY --from=rn-runtime-build /rn-runtime/dist /opt/rn-runtime/dist
ENV RN_RUNTIME_DIST=/opt/rn-runtime/dist

# Copy the current directory contents into the container at /app
COPY ./ /app/
