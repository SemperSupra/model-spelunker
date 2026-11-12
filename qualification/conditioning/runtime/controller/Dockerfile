# syntax=docker/dockerfile:1.7
ARG GO_BASE_IMAGE
FROM ${GO_BASE_IMAGE} AS build
WORKDIR /src
COPY go.mod main.go schema.go openapi.json ./
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -buildvcs=false \
    -ldflags='-s -w' -o /out/conditioning-controller .

FROM scratch
ARG SOURCE_SHA=unqualified
LABEL org.opencontainers.image.source="https://github.com/SemperSupra/model-spelunker" \
      org.opencontainers.image.revision="${SOURCE_SHA}"
COPY --from=build /out/conditioning-controller /conditioning-controller
USER 10001:10001
EXPOSE 8090
ENTRYPOINT ["/conditioning-controller"]
