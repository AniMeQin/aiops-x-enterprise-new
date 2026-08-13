ARG GO_IMAGE=golang:1.24.6-alpine
ARG ALPINE_IMAGE=alpine:3.20.2
ARG GOLANGCI_LINT_VERSION=v2.4.0

FROM ${GO_IMAGE} AS go-quality
ARG GOLANGCI_LINT_VERSION
WORKDIR /src
RUN GOBIN=/usr/local/bin go install github.com/golangci/golangci-lint/v2/cmd/golangci-lint@${GOLANGCI_LINT_VERSION}
COPY agents/edge-agent/go.mod ./go.mod
COPY agents/edge-agent ./

FROM go-quality AS go-build
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/edge-agent ./cmd/edge-agent

FROM ${ALPINE_IMAGE}
RUN addgroup -S aiops && adduser -S -G aiops aiops
COPY --from=go-build /out/edge-agent /usr/local/bin/edge-agent
RUN mkdir -p /var/lib/aiops-x && chown aiops:aiops /var/lib/aiops-x
VOLUME ["/var/lib/aiops-x"]
EXPOSE 9188
USER aiops
ENTRYPOINT ["/usr/local/bin/edge-agent"]
