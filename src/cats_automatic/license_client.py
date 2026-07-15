from __future__ import annotations

import hashlib
import json
import os
import platform
import winreg
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .runtime_paths import app_base_dir


DEFAULT_LICENSE_SERVER_URL = "http://127.0.0.1:8000"
APP_VERSION = "1.5.0"
LOCAL_DEV_LICENSES = {
    "CATS-DEV-AD-ONLY": ("ad_reward",),
    "CATS-DEV-SCRAP-ONLY": ("scrap_ad_battle",),
    "CATS-DEV-FULL-ACCESS": (
        "ad_reward",
        "scrap_ad_battle",
        "scrap_then_ad_reward",
    ),
}


@dataclass(frozen=True)
class LicenseCache:
    license_key: str
    device_id: str
    token: str
    features: tuple[str, ...]
    expires_at: str
    token_expires_at: str
    server_url: str
    last_heartbeat_at: str = ""


@dataclass(frozen=True)
class LicenseResult:
    ok: bool
    status: str
    message: str
    error: str = ""
    cache: LicenseCache | None = None
    event: str = ""

    def allows(self, feature: str) -> bool:
        return self.ok and self.cache is not None and feature in self.cache.features


Transport = Callable[[str, dict[str, str]], dict[str, object]]


def license_cache_path(base_dir: Path | None = None) -> Path:
    return (base_dir or app_base_dir()) / "config" / "license_auth.json"


def get_device_id() -> str:
    values = [
        _machine_guid(),
        os.environ.get("COMPUTERNAME", ""),
        os.environ.get("USERNAME", ""),
        _safe_platform(platform.node),
        _safe_platform(platform.system),
        _safe_platform(platform.machine),
    ]
    raw = "CATSautomatic|" + "|".join(values)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def mask_license_key(license_key: str) -> str:
    parts = license_key.strip().split("-")
    if len(parts) >= 2:
        return "-".join(parts[:2] + ["****"])
    if len(license_key) <= 4:
        return "****"
    return f"{license_key[:4]}****"


def load_license_cache(path: Path | None = None) -> LicenseCache | None:
    target = path or license_cache_path()
    if not target.exists():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        return LicenseCache(
            license_key=str(payload["license_key"]),
            device_id=str(payload["device_id"]),
            token=str(payload["token"]),
            features=tuple(str(item) for item in payload.get("features", [])),
            expires_at=str(payload.get("expires_at", "")),
            token_expires_at=str(payload.get("token_expires_at", "")),
            server_url=str(payload.get("server_url", DEFAULT_LICENSE_SERVER_URL)),
            last_heartbeat_at=str(payload.get("last_heartbeat_at", "")),
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def save_license_cache(cache: LicenseCache, path: Path | None = None) -> Path:
    target = path or license_cache_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(cache)
    payload["features"] = list(cache.features)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def clear_license_cache(path: Path | None = None) -> bool:
    target = path or license_cache_path()
    if not target.exists():
        return False
    target.unlink()
    return True


class LicenseClient:
    def __init__(
        self,
        *,
        server_url: str = DEFAULT_LICENSE_SERVER_URL,
        cache_path: Path | None = None,
        device_id_provider: Callable[[], str] = get_device_id,
        transport: Transport | None = None,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.cache_path = cache_path or license_cache_path()
        self.device_id_provider = device_id_provider
        self.transport = transport or self._post_json

    def activate(self, license_key: str, requested_feature: str) -> LicenseResult:
        key = license_key.strip()
        if not key:
            return LicenseResult(False, "not_activated", "请输入卡密", "license_key_missing", event="license_activate_failed")
        if key in LOCAL_DEV_LICENSES:
            return self._activate_local_dev_license(key, requested_feature)
        device_id = self.device_id_provider()
        try:
            response = self.transport(
                f"{self.server_url}/api/activate",
                {
                    "license_key": key,
                    "device_id": device_id,
                    "app_version": APP_VERSION,
                    "requested_feature": requested_feature,
                },
            )
        except (OSError, ValueError) as exc:
            return LicenseResult(False, "server_error", "授权服务器连接失败", str(exc), event="license_activate_failed")
        if not bool(response.get("ok")):
            return LicenseResult(
                False,
                "activation_failed",
                str(response.get("message", "激活失败")),
                str(response.get("error", "activation_failed")),
                event="license_activate_failed",
            )
        cache = LicenseCache(
            license_key=key,
            device_id=device_id,
            token=str(response.get("token", "")),
            features=tuple(str(item) for item in response.get("features", [])),
            expires_at=str(response.get("expires_at", "")),
            token_expires_at=str(response.get("token_expires_at", "")),
            server_url=self.server_url,
            last_heartbeat_at=_timestamp(),
        )
        save_license_cache(cache, self.cache_path)
        if requested_feature and requested_feature not in cache.features:
            return LicenseResult(False, "feature_denied", "当前卡密未开通该功能", "feature_denied", cache, "license_feature_denied")
        return LicenseResult(True, "activated", str(response.get("message", "激活成功")), cache=cache, event="license_activate_ok")

    def heartbeat(self, cache: LicenseCache | None = None) -> LicenseResult:
        current = cache or load_license_cache(self.cache_path)
        if current is None:
            return LicenseResult(False, "not_activated", "未找到本地授权，请先输入卡密", "license_cache_missing", event="license_heartbeat_failed")
        if current.token == "local-dev-token":
            if os.environ.get("CATS_LICENSE_DEV_BYPASS") != "1":
                return LicenseResult(
                    False,
                    "heartbeat_failed",
                    "本地测试卡密仅允许在开发环境使用",
                    "dev_bypass_env_missing",
                    current,
                    "license_heartbeat_failed",
                )
            updated = LicenseCache(
                **{
                    **asdict(current),
                    "features": current.features,
                    "last_heartbeat_at": _timestamp(),
                }
            )
            save_license_cache(updated, self.cache_path)
            return LicenseResult(True, "active", "本地测试授权心跳通过", cache=updated, event="license_heartbeat_ok")
        try:
            response = self.transport(
                f"{current.server_url.rstrip('/')}/api/heartbeat",
                {
                    "license_key": current.license_key,
                    "device_id": current.device_id,
                    "token": current.token,
                    "app_version": APP_VERSION,
                },
            )
        except (OSError, ValueError) as exc:
            return LicenseResult(False, "heartbeat_failed", "授权服务器连接失败", str(exc), current, "license_heartbeat_failed")
        if not bool(response.get("ok")):
            return LicenseResult(
                False,
                "heartbeat_failed",
                str(response.get("message", "授权心跳失败")),
                str(response.get("error", "heartbeat_failed")),
                current,
                "license_heartbeat_failed",
            )
        updated = LicenseCache(
            license_key=current.license_key,
            device_id=current.device_id,
            token=current.token,
            features=tuple(str(item) for item in response.get("features", current.features)),
            expires_at=str(response.get("expires_at", current.expires_at)),
            token_expires_at=str(response.get("token_expires_at", current.token_expires_at)),
            server_url=current.server_url,
            last_heartbeat_at=_timestamp(),
        )
        save_license_cache(updated, self.cache_path)
        return LicenseResult(True, "active", str(response.get("message", "心跳通过")), cache=updated, event="license_heartbeat_ok")

    def _activate_local_dev_license(
        self,
        license_key: str,
        requested_feature: str,
    ) -> LicenseResult:
        if os.environ.get("CATS_LICENSE_DEV_BYPASS") != "1":
            return LicenseResult(
                False,
                "activation_failed",
                "本地测试卡密仅允许在开发环境使用",
                "dev_bypass_env_missing",
                event="license_activate_failed",
            )
        features = LOCAL_DEV_LICENSES[license_key]
        cache = LicenseCache(
            license_key=license_key,
            device_id=self.device_id_provider(),
            token="local-dev-token",
            features=features,
            expires_at="2099-12-31T23:59:59+00:00",
            token_expires_at="2099-12-31T23:59:59+00:00",
            server_url=self.server_url,
            last_heartbeat_at=_timestamp(),
        )
        save_license_cache(cache, self.cache_path)
        if requested_feature not in features:
            return LicenseResult(
                False,
                "feature_denied",
                "当前测试卡密未开通该功能",
                "feature_denied",
                cache,
                "license_feature_denied",
            )
        return LicenseResult(
            True,
            "activated",
            "本地测试卡密激活成功",
            cache=cache,
            event="license_activate_ok",
        )

    @staticmethod
    def _post_json(url: str, payload: dict[str, str]) -> dict[str, object]:
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=5) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                return json.loads(body)
            except json.JSONDecodeError as decode_error:
                raise OSError(f"HTTP {exc.code}") from decode_error
        except URLError as exc:
            raise OSError(str(exc.reason)) from exc
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise ValueError("授权服务器返回了无效 JSON") from exc


def authorize_strategy(
    *,
    strategy: str,
    license_key: str | None,
    server_url: str,
    cache_path: Path | None = None,
    skip_for_dev: bool = False,
    client: LicenseClient | None = None,
) -> LicenseResult:
    requested_strategy = strategy
    strategy = feature_for_strategy(strategy)
    if skip_for_dev:
        if os.environ.get("CATS_LICENSE_DEV_BYPASS") == "1":
            cache = LicenseCache("DEV-BYPASS", "dev", "", (strategy,), "", "", server_url)
            return LicenseResult(True, "dev_bypass", "开发授权绕过已启用", cache=cache, event="license_dev_bypass")
        return LicenseResult(False, "bypass_denied", "开发授权绕过未启用", "dev_bypass_env_missing", event="license_activate_failed")
    active_client = client or LicenseClient(server_url=server_url, cache_path=cache_path)
    result = (
        active_client.activate(license_key, strategy)
        if license_key
        else active_client.heartbeat()
    )
    if result.ok and not result.allows(strategy):
        return LicenseResult(False, "feature_denied", "当前卡密未开通 strategy", "feature_denied", result.cache, "license_feature_denied")
    return result


def feature_for_strategy(strategy: str) -> str:
    return "ad_reward" if strategy == "scrap_then_ad_reward_v2" else strategy


def _machine_guid() -> str:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
            return str(winreg.QueryValueEx(key, "MachineGuid")[0])
    except OSError:
        return ""


def _safe_platform(getter: Callable[[], str]) -> str:
    try:
        return getter() or ""
    except Exception:
        return ""


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
