# --- Build stage ---
FROM golang:1.22-alpine AS builder
WORKDIR /app
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o /server .

# --- Run stage ---
FROM alpine:3.20
WORKDIR /app
COPY --from=builder /server ./server
COPY web ./web
EXPOSE 8080
ENV PORT=8080
ENTRYPOINT ["./server"]