# syntax=docker/dockerfile:1.7
# BASE_IMAGE MUST be an exact OCI digest, never a floating tag.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
LABEL org.opencontainers.image.source="https://github.com/SemperSupra/model-spelunker" \
      org.opencontainers.image.description="Disposable ComfyUI conditioning runtime with synthetic Torch fixture" \
      org.opencontainers.image.licenses="GPL-3.0-or-later"
COPY --chown=1000:1000 toy_node/__init__.py /opt/bundled_nodes/conditioning_toy_fixture/__init__.py
# Upstream entrypoint links only our audited fixture. No bundled manager, auto fetch,
# custom-node pip installation or startup mutations outside the ephemeral /data.
ENV COMFYUI_ENABLE_MANAGER=false \
    COMFYUI_BUNDLED_NODES=conditioning_toy_fixture \
    COMFYUI_PRELOAD_NODES="" \
    COMFYUI_INSTALL_NODE_REQUIREMENTS=false \
    COMFYUI_ARGS="--offline" \
    COMFYUI_CHOWN_DATA=false \
    COMFYUI_CPU=true \
    COMFYUI_FORCE_FP32=true \
    COMFYUI_LISTEN=0.0.0.0 \
    COMFYUI_PORT=8188
