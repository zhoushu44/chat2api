FROM golang:1.26-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /chatgpt2api-go ./cmd/server

FROM alpine:3.19
RUN apk --no-cache add ca-certificates
COPY --from=builder /chatgpt2api-go /chatgpt2api-go
COPY web_dist /web_dist
EXPOSE 3077 6060
VOLUME ["/data"]
ENV STORAGE_BACKEND=json
# 监听 0.0.0.0:3077（Go net/http 中 -addr ":3077" 绑定所有网卡）
ENTRYPOINT ["/chatgpt2api-go", "-config", "/data/config.json", "-addr", ":3077"]
