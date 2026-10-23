from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from . import APP_NAME


def default_app_data_dir() -> Path:
    base = os.environ.get("STOCK_APP_DATA_DIR") or os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "StockRecommendationEngine"
    return Path.home() / "AppData" / "Local" / "StockRecommendationEngine"


@dataclass(frozen=True)
class AppConfig:
    repo_root: Path
    app_data_dir: Path

    @property
    def database_path(self) -> Path:
        return self.app_data_dir / "stock_recommendation_engine.sqlite3"

    @property
    def log_dir(self) -> Path:
        return self.app_data_dir / "logs"

    @property
    def display_name(self) -> str:
        return APP_NAME


def load_config(repo_root: Path | None = None, app_data_dir: Path | None = None) -> AppConfig:
    env_root = os.environ.get("STOCK_APP_REPO_ROOT")
    root = repo_root or (Path(env_root) if env_root else Path(__file__).resolve().parents[1])
    data_dir = app_data_dir or default_app_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "logs").mkdir(parents=True, exist_ok=True)
    return AppConfig(repo_root=root, app_data_dir=data_dir)
