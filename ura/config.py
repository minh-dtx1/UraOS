"""Cấu hình Ura, đọc từ biến môi trường hoặc file .env."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Trình đọc .env tối giản (không cần thư viện ngoài). Không ghi đè biến đã có."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.split(" #", 1)[0].strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


_load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    model: str = os.environ.get("URA_MODEL", "claude-opus-5-5")
    effort: str = os.environ.get("URA_EFFORT", "medium")
    user_name: str = os.environ.get("URA_USER_NAME", "sếp")
    web_search: bool = os.environ.get("URA_WEB_SEARCH", "1") not in ("0", "false", "no")
    port: int = int(os.environ.get("URA_PORT", "8000"))
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("URA_DATA_DIR", ROOT / "data")))
    max_tokens: int = 32000
    # Giới hạn số vòng gọi công cụ trong một lượt để tránh lặp vô hạn
    max_tool_rounds: int = 12


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
