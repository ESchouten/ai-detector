ARG TARGETARCH
# Update these digests deliberately after qualifying the upstream runtime.
ARG ULTRALYTICS_TAG_AMD64=latest@sha256:ed0f6dada510fb220d864d0d72d0dba356ed58b3845940999fd8ba64255851b5
ARG ULTRALYTICS_TAG_ARM64=latest-nvidia-arm64@sha256:35d9e3138daad4e8c40c8b68e2c4627c609b2f9f00f2a9db6ee8634b39dbe7f6

FROM --platform=linux/amd64 ultralytics/ultralytics:${ULTRALYTICS_TAG_AMD64} AS runtime-amd64
FROM --platform=linux/arm64 ultralytics/ultralytics:${ULTRALYTICS_TAG_ARM64} AS runtime-arm64
FROM runtime-${TARGETARCH} AS runtime
ARG TARGETARCH

# Replace the base image's uv, which takes precedence over /bin on PATH.
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /uvx /usr/local/bin/

WORKDIR /app

# Lock torch versions to prevent replacement by system packages
RUN pip freeze | grep -E "^(torch|torchvision|torchaudio)" > constraints.txt

# Install the application directly into the ultralytics Python environment.
# amd64 images install the project NVIDIA extra explicitly; arm64 images
# keep the ONNX runtime stack provided by the Ultralytics base image.
# --break-system-packages is needed because Debian marks system Python as externally managed
COPY pyproject.toml /app/
COPY vendor/cutie/ /app/vendor/cutie/
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
COPY --chown=nonroot:nonroot . /app
ARG REF_NAME=main
RUN printf 'TYPE = "cuda"\nREF_NAME = "%s"\n' "$REF_NAME" > /app/src/aidetector/version.py \
    && uv pip install --system --break-system-packages --no-deps .

RUN mkdir -p /data && chown nonroot:nonroot /app /data

# Use the non-root user to run our application
USER nonroot
WORKDIR /data

# Run the application
CMD ["python3", "-m", "aidetector"]
