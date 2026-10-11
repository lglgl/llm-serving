# ============================================================
# Stage 1: 从网络下载 GGUF 模型
# ============================================================
FROM alpine:3.20 AS model-downloader

RUN apk add --no-cache curl

RUN mkdir -p /models && \
    curl -fL --retry 3 \
    "https://huggingface.co/Qwen/Qwen2-0.5B-Instruct-GGUF/resolve/main/qwen2-0_5b-instruct-q4_k_m.gguf" \
    -o /models/qwen2-0_5b-instruct-q4_k_m.gguf

# ============================================================
# Stage 2: 使用官方 llama.cpp 服务镜像
# ============================================================
FROM ghcr.io/ggml-org/llama.cpp:server

COPY --from=model-downloader \
    /models/qwen2-0_5b-instruct-q4_k_m.gguf \
    /models/qwen2-0_5b-instruct-q4_k_m.gguf

EXPOSE 8080

CMD ["-m", "/models/qwen2-0_5b-instruct-q4_k_m.gguf", "--host", "0.0.0.0", "--port", "8080", "--alias", "qwen2:0.5b", "-c", "2048"]