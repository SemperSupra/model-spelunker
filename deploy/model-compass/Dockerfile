# syntax=docker/dockerfile:1.7
# Source: SemperSupra/model-spelunker#304. No model weights or private data.
# Release promotion MUST pin both build inputs and the resulting OCI digest.
FROM --platform=$BUILDPLATFORM golang:1.27.4-alpine AS build
ARG TARGETOS
ARG TARGETARCH
ARG SOURCE_REVISION=unqualified
WORKDIR /src
COPY cmd/model-compass ./cmd/model-compass
COPY cmd/compass-http ./cmd/compass-http
RUN set -eu; \
    cd /src/cmd/model-compass; \
    CGO_ENABLED=0 GOOS="$TARGETOS" GOARCH="$TARGETARCH" GOPROXY=off GOSUMDB=off \
      go build -trimpath -buildvcs=false -ldflags="-s -w" -o /out/model-compass .
RUN set -eu; \
    cd /src/cmd/compass-http; \
    CGO_ENABLED=0 GOOS="$TARGETOS" GOARCH="$TARGETARCH" GOPROXY=off GOSUMDB=off \
      go build -trimpath -buildvcs=false -ldflags="-s -w" -o /out/compass-http .

FROM scratch
ARG SOURCE_REVISION=unqualified
LABEL org.opencontainers.image.source="https://github.com/SemperSupra/model-spelunker" \
      org.opencontainers.image.description="Standalone Model Compass read-only OCI service" \
      org.opencontainers.image.revision="$SOURCE_REVISION"
COPY --from=build /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY --from=build /out/model-compass /usr/local/bin/model-compass
COPY --from=build /out/compass-http /usr/local/bin/compass-http
USER 65532:65532
ENV COMPASS_LISTEN=:8088 \
    COMPASS_TOKEN_FILE=/run/secrets/compass_token \
    COMPASS_SNAPSHOT_FILE=/state/snapshot.json \
    COMPASS_MODEL_BIN=/usr/local/bin/model-compass
EXPOSE 8088/tcp
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["/usr/local/bin/compass-http","-self-check"]
ENTRYPOINT ["/usr/local/bin/compass-http"]
