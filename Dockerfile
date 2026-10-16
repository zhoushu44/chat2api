FROM golang:1.26-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /chatgpt2api-go ./cmd/server

# 以官方 23.0 运行层为基底，替换二进制（保留 entrypoint/supervisord/regiforge/chrome）
FROM zhoushu1/chat2api:23.0
COPY --from=builder /chatgpt2api-go /chatgpt2api-go
