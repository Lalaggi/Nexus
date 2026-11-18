"""Runtime configuration and filesystem layout."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ASSISTANT_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "0.0.0.0"
    port: int = 8848
    data_dir: Path = PROJECT_ROOT / "data"
    home: Path | None = None

    searxng_url: str = "http://127.0.0.1:8888"
    sandbox_image: str = "localhost/assistant-code-sandbox:latest"
    sandbox_enabled: bool = True
    sandbox_memory: str = "768m"
    sandbox_cpus: str = "1.0"
    sandbox_timeout: int = 90
    sandbox_account: str = "sandbox"
    sandbox_podman_wrapper: str = "/usr/local/bin/assistant-sandbox-podman"
    sandbox_network: bool = True
    sandbox_dns: str = "1.1.1.1,9.9.9.9"

    max_tool_steps: int = 10
    max_search_results: int = 6
    max_upload_mb: int = 50
    user_name: str = "Ellie"
    assistant_name: str = "Assistant"
    password: str = ""
    cookie_secure: bool = False
    # Comma-separated origins allowed to call the API from a packaged app.
    # The Capacitor Android WebView loads file:// assets (Origin: null) and
    # talks to a user-supplied server over HTTP(S).
    cors_origins: str = "*"
    provider: str = "auto"
    temperature: float = 0.6
    max_tokens: int = 8192
    request_timeout: float = 300.0

    openrouter_api_key: str = ""
    nvidia_api_key: str = ""

    # Sensitive database fields are encrypted at rest. Set a Fernet key or a
    # passphrase here, or leave empty to use the key file below.
    encryption_key: str = ""
    secret_key_file: Path | None = None

    # Optional endpoint overrides. Useful for proxies, self-hosted NIM, or a
    # local OpenAI-compatible test server; empty means use the provider default.
    nim_base_url: str = ""
    openrouter_base_url: str = ""

    @property
    def uploads_dir(self) -> Path:
        return self.home / "useruploads"  # type: ignore[operator]

    @property
    def outputs_dir(self) -> Path:
        return self.home / "outputs"  # type: ignore[operator]

    @property
    def tempuploads_dir(self) -> Path:
        return self.home / "tempuploads"  # type: ignore[operator]

    @property
    def workspaces_dir(self) -> Path:
        return self.home / ".workspaces"  # type: ignore[operator]

    def chat_uploads_dir(self, chat_id: str) -> Path:
        return self.uploads_dir / chat_id

    def chat_outputs_dir(self, chat_id: str) -> Path:
        return self.outputs_dir / chat_id

    def chat_workspace_dir(self, chat_id: str) -> Path:
        return self.workspaces_dir / chat_id

    @property
    def db_path(self) -> Path:
        return self.data_dir / "assistant.db"

    @property
    def secret_key_path(self) -> Path:
        if self.secret_key_file is not None:
            return self.secret_key_file.expanduser().resolve()
        config_home = Path(
            os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
        ).expanduser()
        return config_home / "assistant" / "secret.key"

    @property
    def web_dist(self) -> Path:
        return PROJECT_ROOT / "web" / "dist"

    @property
    def nim_key(self) -> str:
        return (
            os.getenv("NVIDIA_API_KEY")
            or os.getenv("NIM_API_KEY")
            or self.nvidia_api_key
        ).strip()

    @property
    def openrouter_key(self) -> str:
        return (os.getenv("OPENROUTER_API_KEY") or self.openrouter_api_key).strip()

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


def _prepare_dirs(home: Path) -> bool:
    try:
        (home / "useruploads").mkdir(parents=True, exist_ok=True)
        (home / "tempuploads").mkdir(parents=True, exist_ok=True)
        (home / "outputs").mkdir(parents=True, exist_ok=True)
        probe = home / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


@lru_cache(maxsize=1)
def load_config() -> Config:
    cfg = Config()
    cfg.data_dir = cfg.data_dir.expanduser().resolve()
    cfg.data_dir.mkdir(parents=True, exist_ok=True)

    preferred = (cfg.home or Path("/home/assistant")).expanduser()
    if not _prepare_dirs(preferred):
        fallback = cfg.data_dir / "home"
        _prepare_dirs(fallback)
        preferred = fallback
    cfg.home = preferred

    cfg.workspaces_dir.mkdir(parents=True, exist_ok=True)
    return cfg


CONFIG = load_config()
