# syntax=docker/dockerfile:1.7
# BASE_IMAGE MUST be an exact OCI digest, never a floating tag.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
ARG SOURCE_SHA=unqualified
ARG COMFYUI_CPU_MODE=true
LABEL org.opencontainers.image.source="https://github.com/SemperSupra/model-spelunker" \
      org.opencontainers.image.description="Disposable ComfyUI conditioning runtime with synthetic Torch fixture" \
      org.opencontainers.image.licenses="GPL-3.0-or-later" \
      org.opencontainers.image.revision="${SOURCE_SHA}"
COPY --chown=1000:1000 toy_node/ /opt/bundled_nodes/conditioning_toy_fixture/
# Upstream entrypoint links only our audited fixture. No bundled manager, auto fetch,
# custom-node pip installation or startup mutations outside the ephemeral /data.
ENV COMFYUI_ENABLE_MANAGER=false \
    COMFYUI_BUNDLED_NODES=conditioning_toy_fixture \
    COMFYUI_PRELOAD_NODES="" \
    COMFYUI_INSTALL_NODE_REQUIREMENTS=false \
    COMFYUI_ARGS="--disable-api-nodes" \
    COMFYUI_CHOWN_DATA=false \
    COMFYUI_CPU=${COMFYUI_CPU_MODE} \
    COMFYUI_FORCE_FP32=true \
    COMFYUI_LISTEN=0.0.0.0 \
    COMFYUI_PORT=8188
