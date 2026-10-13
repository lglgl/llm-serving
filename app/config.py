from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # llama.cpp OpenAI-compatible API
    # 默认面向宿主机本地开发；Compose 和 Kubernetes 会显式覆盖为容器服务地址。
    llama_base_url: str = "http://127.0.0.1:8081/v1"

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
