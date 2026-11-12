# syntax=docker/dockerfile:1.7
ARG GO_BASE_IMAGE
FROM ${GO_BASE_IMAGE} AS build
WORKDIR /src
COPY go.mod main.go ./
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -buildvcs=false \
    -ldflags='-s -w' -o /out/conditioning-controller .

FROM scratch
COPY --from=build /out/conditioning-controller /conditioning-controller
USER 10001:10001
EXPOSE 8090
ENTRYPOINT ["/conditioning-controller"]
