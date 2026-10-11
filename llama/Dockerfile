FROM ghcr.io/ggml-org/llama.cpp:server

WORKDIR /app

COPY models/qwen2-0_5b-instruct-q4_k_m.gguf /models/qwen2-0_5b-instruct-q4_k_m.gguf

EXPOSE 8090

CMD ["-m", "/models/qwen2-0_5b-instruct-q4_k_m.gguf", "--host", "0.0.0.0", "--port", "8080", "--alias", "qwen2:0.5b", "-c", "2048"]