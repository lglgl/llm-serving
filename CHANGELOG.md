# Changelog

## 2026-10-29

### Current architecture

- The active inference path is FastAPI → LiteLLM → vLLM via the `hosted_vllm/` provider.
- The public alias `qwen3:8b` routes to the configured `VLLM_MODEL`.
- `/v1/models` lists the configured default alias; `/health` checks vLLM readiness.
- Removed llama.app configuration, alias routing, and health reporting after initially adding it as an optional backend.
- Updated environment documentation, startup commands, Docker instructions, and API test expectations.

### Earlier migration in this release

- Replaced the Ollama-specific inference integration with LiteLLM's async completion interface.
- Added vLLM and initially added llama.app / llama.cpp as optional local backends.
- Removed the Ollama client wrapper.
- vLLM runs as a separate inference server and is reached through its OpenAI-compatible API.
