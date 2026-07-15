"""Minimal YandexGPT completion client.

The client is optional. If credentials are absent, description_builder.py falls
back to deterministic rule-based descriptions and marks rows for review.
"""
from __future__ import annotations

import configparser
import logging
import time
from dataclasses import dataclass
from typing import Optional

import requests

from paths import get_secret


@dataclass
class YandexGPTConfig:
    token: str
    folder_id: str
    model_uri: str
    auth_type: str = "Bearer"
    endpoint: str = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
    temperature: float = 0.2
    max_tokens: int = 900
    retries: int = 3
    retry_delay_sec: float = 2.0
    request_delay_sec: float = 0.2
    timeout_sec: float = 60.0


class YandexGPTClient:
    def __init__(self, cfg: YandexGPTConfig, logger: Optional[logging.Logger] = None):
        self.cfg = cfg
        self.log = logger or logging.getLogger(__name__)
        self.session = requests.Session()
        if cfg.auth_type.lower() == "api-key":
            self.session.headers.update({"Authorization": f"Api-Key {cfg.token}"})
        else:
            self.session.headers.update({"Authorization": f"Bearer {cfg.token}"})
        self.session.headers.update({"Content-Type": "application/json"})

    @classmethod
    def from_config(cls, config: configparser.ConfigParser, logger: Optional[logging.Logger] = None) -> Optional["YandexGPTClient"]:
        token = get_secret(
            config,
            "YANDEXGPT_TOKEN",
            "yandexgpt_iam_token.txt",
            section="yandexgpt",
            option="token",
        )
        folder_id = get_secret(
            config,
            "YANDEXGPT_FOLDER_ID",
            "yandexgpt_folder_id.txt",
            section="yandexgpt",
            option="folder_id",
        )
        if not token or not folder_id:
            return None
        model_uri = config.get("yandexgpt", "model_uri", fallback="").strip()
        if not model_uri:
            model_uri = f"gpt://{folder_id}/yandexgpt-lite/latest"
        cfg = YandexGPTConfig(
            token=token,
            folder_id=folder_id,
            model_uri=model_uri,
            auth_type=config.get("yandexgpt", "auth_type", fallback="Bearer"),
            endpoint=config.get("yandexgpt", "endpoint", fallback="https://llm.api.cloud.yandex.net/foundationModels/v1/completion"),
            temperature=config.getfloat("yandexgpt", "temperature", fallback=0.2),
            max_tokens=config.getint("yandexgpt", "max_tokens", fallback=900),
            retries=config.getint("yandexgpt", "retries", fallback=3),
            retry_delay_sec=config.getfloat("yandexgpt", "retry_delay_sec", fallback=2.0),
            request_delay_sec=config.getfloat("yandexgpt", "request_delay_sec", fallback=0.2),
            timeout_sec=config.getfloat("yandexgpt", "timeout_sec", fallback=60.0),
        )
        return cls(cfg, logger=logger)

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "modelUri": self.cfg.model_uri,
            "completionOptions": {
                "stream": False,
                "temperature": self.cfg.temperature,
                "maxTokens": str(self.cfg.max_tokens),
            },
            "messages": [
                {"role": "system", "text": system_prompt},
                {"role": "user", "text": user_prompt},
            ],
        }
        for attempt in range(1, self.cfg.retries + 1):
            try:
                r = self.session.post(self.cfg.endpoint, json=payload, timeout=self.cfg.timeout_sec)
                if r.status_code in {429, 500, 502, 503, 504}:
                    time.sleep(self.cfg.retry_delay_sec * attempt)
                    continue
                r.raise_for_status()
                time.sleep(self.cfg.request_delay_sec)
                data = r.json()
                alternatives = data.get("result", {}).get("alternatives", [])
                if not alternatives:
                    return ""
                return str(alternatives[0].get("message", {}).get("text", "")).strip()
            except Exception as exc:
                self.log.warning("YandexGPT attempt failed attempt=%s error=%r", attempt, exc)
                time.sleep(self.cfg.retry_delay_sec * attempt)
        return ""
