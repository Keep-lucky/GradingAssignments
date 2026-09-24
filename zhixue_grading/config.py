"""本地运行配置读取。"""

import json
import os
from pathlib import Path
from dataclasses import dataclass


CONFIG_FILE_NAME = "config.json"
COOKIE_ENV_NAME = "ZHIXUE_COOKIE"
OPENAI_API_KEY_ENV_NAME = "OPENAI_API_KEY"


@dataclass(frozen=True)
class GradingConfig:
    base_url: str
    api_key: str
    model: str
    prompt: str
    timeout_seconds: int = 60


def load_cookie(config_path: Path | None = None) -> str:
    """读取 Cookie，优先环境变量，否则读取本地 config.json。"""
    cookie = os.getenv(COOKIE_ENV_NAME, "").strip()
    if cookie:
        return cookie

    path = config_path or Path.cwd() / CONFIG_FILE_NAME
    try:
        with path.open(encoding="utf-8") as config_file:
            config = json.load(config_file)
    except FileNotFoundError as error:
        raise RuntimeError(
            "未找到登录配置。请设置环境变量 ZHIXUE_COOKIE，或创建 "
            f"{path.name} 并填入 cookies 字段。"
        ) from error
    except json.JSONDecodeError as error:
        raise RuntimeError(f"配置文件格式错误：{path}") from error

    cookie = str(config.get("cookies", "")).strip()
    if not cookie:
        raise RuntimeError(f"配置文件缺少非空的 cookies 字段：{path}")
    return cookie


def load_grading_config(config_path: Path | None = None) -> GradingConfig:
    """读取 OpenAI 兼容视觉评分配置；环境变量可覆盖配置文件密钥。"""
    path = config_path or Path.cwd() / CONFIG_FILE_NAME
    try:
        with path.open(encoding="utf-8") as config_file:
            config = json.load(config_file)
        service = config["openai_compatible"]
        rules = config["grading"]
        api_key = os.getenv(OPENAI_API_KEY_ENV_NAME, service.get("api_key", "")).strip()
        result = GradingConfig(
            base_url=str(service["base_url"]).rstrip("/"),
            api_key=api_key,
            model=str(service["model"]),
            prompt=str(rules["prompt"]),
            timeout_seconds=int(service.get("timeout_seconds", 60)),
        )
    except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError("缺少或无法解析 AI 评分配置，请检查 config.json。") from error
    if not result.api_key:
        raise RuntimeError("缺少 API 密钥。请在 config.json 填写 api_key 或设置 OPENAI_API_KEY。")
    return result
