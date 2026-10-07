ARG TARGETARCH
# Update these digests deliberately after qualifying the upstream runtime.
ARG ULTRALYTICS_TAG_AMD64=latest@sha256:ed0f6dada510fb220d864d0d72d0dba356ed58b3845940999fd8ba64255851b5

# Multi-platform Node 24 base; update deliberately alongside container smoke checks.
FROM node:24-bookworm-slim@sha256:0e0ff40c39bc087845bfb27465a0df4ea419520094bc35842ff83dd8cbe6f9b6 AS node

FROM node AS web

ENV PNPM_HOME=/pnpm
ENV PATH=$PNPM_HOME:$PATH

RUN corepack enable

WORKDIR /app/web

COPY web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml web/.npmrc ./
COPY web/patches ./patches
RUN pnpm install --frozen-lockfile

COPY web .
COPY config /app/config

# As the desktop build does: name the version, and keep the bundled presets unless this is a release.
ARG REF_NAME=main
RUN case "$REF_NAME" in app/v*) preview=false ;; *) preview=true ;; esac \
    && printf "export const version = '%s';\nexport const preview = %s;\n" "$REF_NAME" "$preview" > src/lib/version.ts

# The build needs more memory than Node allows itself on a host with 8 GB.
RUN pnpm exec svelte-kit sync \
    && NODE_OPTIONS=--max-old-space-size=4096 pnpm build \
    && pnpm prune --prod --ignore-scripts

FROM --platform=linux/amd64 ultralytics/ultralytics:${ULTRALYTICS_TAG_AMD64} AS runtime-amd64

# ARM64 is for Jetson Orin and Thor with JetPack 7.2, which run the standard ARM64 CUDA 13
# software. This follows Ultralytics' recipe for it and leaves out the many gigabytes of
# NVIDIA's general PyTorch image that the detector never loads.
FROM --platform=linux/arm64 ubuntu:24.04@sha256:534baea6a22c03a63003dbc8dbe78fe34bc0d7e595d9a9dc9834884ff530eb55 AS runtime-arm64
ENV PIP_BREAK_SYSTEM_PACKAGES=1 PIP_NO_CACHE_DIR=1
RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates libgl1 libglib2.0-0 python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*
# One layer each: a registry keeps what has arrived, so a download or upload that is cut off
# repeats a few gigabytes at most, and a newer TensorRT replaces only its own layer.
RUN pip install torch==2.14.1 torchvision==0.29.1 --index-url https://download.pytorch.org/whl/cu130
RUN pip install onnx onnxslim \
        https://github.com/ultralytics/assets/releases/download/v0.0.0/onnxruntime_gpu-1.24.0-cp312-cp312-linux_aarch64.whl
# TensorRT 10, the line JetPack supports; 11 does not run there.
RUN pip install --extra-index-url https://pypi.nvidia.com tensorrt-cu13==10.15.1.29
# NVIDIA's own base images say this; without it the NVIDIA runtime passes no GPU in.
ENV NVIDIA_VISIBLE_DEVICES=all NVIDIA_DRIVER_CAPABILITIES=compute,utility

FROM runtime-${TARGETARCH} AS runtime
ARG TARGETARCH

# Replace the base image's uv, which takes precedence over /bin on PATH.
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /uvx /usr/local/bin/

WORKDIR /app/detector

# Lock torch versions to prevent replacement by system packages. As name==version: the ARM64
# base installed them from wheel files that are gone, which a plain freeze would point at.
RUN pip list --format=freeze | grep -E "^(torch|torchvision|torchaudio)==" > constraints.txt

# Install the detector directly into the ultralytics Python environment.
# amd64 images install the project NVIDIA extra explicitly; arm64 images
# keep the ONNX runtime installed with their base above.
# --break-system-packages is needed because Debian marks system Python as externally managed
COPY detector/pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ "$TARGETARCH" = "amd64" ]; then \
        uv pip install --system --break-system-packages --constraint constraints.txt -r pyproject.toml --extra nvidia; \
    else \
        uv pip install --system --break-system-packages --constraint constraints.txt -r pyproject.toml; \
    fi

# Setup a non-root user
RUN groupadd --system --gid 999 nonroot \
    && useradd --system --gid 999 --uid 999 --create-home nonroot

# Give nonroot user write access to ultralytics weights directory (for model downloads)
RUN mkdir -p /ultralytics/weights && chown -R nonroot:nonroot /ultralytics

# Source edits and release tags do not invalidate the dependency layer.
COPY --chown=nonroot:nonroot detector ./
ARG REF_NAME=main
RUN printf 'TYPE = "cuda"\nREF_NAME = "%s"\n' "$REF_NAME" > src/aidetector/version.py \
    && uv pip install --system --break-system-packages --no-deps . \
    # On a Jetson the detector also prepares TensorRT engines, and runs on PyTorch until they are ready.
    && if [ "$TARGETARCH" = "arm64" ]; then \
        printf '#!/bin/sh\nexec aidetector --prefer-tensorrt "$@"\n' > /app/aidetector && chmod +x /app/aidetector; \
    else \
        ln -s "$(command -v aidetector)" /app/aidetector; \
    fi

# The web application, which starts the detector and keeps it running. Node may listen on
# port 80 without being root, also when the container shares the host's network.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
RUN apt-get update \
    && apt-get install --yes --no-install-recommends libcap2-bin \
    && rm -rf /var/lib/apt/lists/* \
    && setcap cap_net_bind_service=+ep /usr/local/bin/node
COPY --from=web --chown=nonroot:nonroot /app/web/build /app/build
COPY --from=web --chown=nonroot:nonroot /app/web/package.json /app/web/node-server.mjs /app/
COPY --from=web --chown=nonroot:nonroot /app/web/node_modules /app/node_modules

ENV NODE_ENV=production
ENV HOST=0.0.0.0
ENV PORT=3000
ENV AIDETECTOR_EXECUTABLE=/app/aidetector

RUN mkdir -p /data && chown nonroot:nonroot /app /data

# Use the non-root user to run our application
USER nonroot
WORKDIR /data

EXPOSE 3000

CMD ["node", "/app/node-server.mjs"]
