from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    vllm_api_base: str = "http://localhost:8001/v1"
    vllm_api_key: str = ""
    vllm_model: str = "Qwen/Qwen3-8B"
    default_model: str = "qwen3:8b"
    request_timeout: float = 300.0

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()


def resolve_litellm_target(model: str) -> tuple[str, str, str]:
    """Return the LiteLLM vLLM model, API base and key for a public alias."""
    if model in {settings.default_model, settings.vllm_model}:
        return (
            f"hosted_vllm/{settings.vllm_model}",
            settings.vllm_api_base.rstrip("/"),
            settings.vllm_api_key or "EMPTY",
        )
    raise ValueError(f"Unknown model alias: {model}")
