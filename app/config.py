from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # llama.cpp OpenAI-compatible API
    llama_base_url: str = "http://llm-serving-llama:8080/v1"

    # 必须与 llama.cpp 服务端配置的模型别名一致
    default_model: str = "qwen2:0.5b"

    # 模型请求超时时间（秒）
    request_timeout: float = 300.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
