# syntax=docker/dockerfile:1.7
ARG PYTHON_BASE_IMAGE
ARG ORAS_IMAGE
FROM ${ORAS_IMAGE} AS oras
FROM ${PYTHON_BASE_IMAGE}
ARG SOURCE_SHA=unqualified
LABEL org.opencontainers.image.source="https://github.com/SemperSupra/model-spelunker" \
      org.opencontainers.image.revision="${SOURCE_SHA}"
ARG MAF_COMMIT=6bc5750dcd947cbbf8b3a11e80afbabd81c19ed6
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN git init -q /opt/maf \
    && git -C /opt/maf remote add origin https://github.com/SemperSupra/model-artifact-foundry.git \
    && git -C /opt/maf fetch -q --depth 1 origin "${MAF_COMMIT}" \
    && git -C /opt/maf checkout -q --detach FETCH_HEAD \
    && test "$(git -C /opt/maf rev-parse HEAD)" = "$MAF_COMMIT" \
    && python3 -m py_compile /opt/maf/tools/hydrate.py
COPY --from=oras /bin/oras /usr/local/bin/oras
COPY gate.py /opt/conditioning/gate.py
RUN chmod 0555 /usr/local/bin/oras /opt/conditioning/gate.py
USER 10001:10001
WORKDIR /opt/conditioning
ENTRYPOINT ["python3", "/opt/conditioning/gate.py"]
