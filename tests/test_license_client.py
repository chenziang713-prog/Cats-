from __future__ import annotations

import json
from pathlib import Path

import pytest

from cats_automatic.license_client import (
    LicenseCache,
    LicenseClient,
    authorize_strategy,
    clear_license_cache,
    get_device_id,
    load_license_cache,
    mask_license_key,
)
from cats_automatic.main import authorize_strategy_run, build_parser


def test_get_device_id_is_stable_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cats_automatic.license_client._machine_guid", lambda: "guid")
    monkeypatch.setattr("cats_automatic.license_client.platform.node", lambda: "node")
    monkeypatch.setattr("cats_automatic.license_client.platform.system", lambda: "Windows")
    monkeypatch.setattr("cats_automatic.license_client.platform.machine", lambda: "AMD64")
    monkeypatch.setenv("COMPUTERNAME", "pc")
    monkeypatch.setenv("USERNAME", "user")

    first = get_device_id()
    second = get_device_id()

    assert first == second
    assert len(first) == 64
    assert "guid" not in first


def test_activate_success_saves_cache(tmp_path: Path) -> None:
    payloads: list[dict[str, str]] = []

    def transport(url: str, payload: dict[str, str]) -> dict[str, object]:
        payloads.append(payload)
        assert url == "http://127.0.0.1:8000/api/activate"
        return _activate_ok()

    cache_path = tmp_path / "config" / "license_auth.json"
    client = LicenseClient(
        cache_path=cache_path,
        device_id_provider=lambda: "device-hash",
        transport=transport,
    )

    result = client.activate("CATS-ABCD-EFGH", "scrap_then_ad_reward")

    assert result.ok
    assert result.event == "license_activate_ok"
    assert load_license_cache(cache_path) == result.cache
    assert payloads[0]["device_id"] == "device-hash"
    assert payloads[0]["requested_feature"] == "scrap_then_ad_reward"


def test_activate_failure_does_not_save_token(tmp_path: Path) -> None:
    cache_path = tmp_path / "license_auth.json"
    client = LicenseClient(
        cache_path=cache_path,
        transport=lambda *_: {"ok": False, "error": "license_expired", "message": "卡密已过期"},
    )

    result = client.activate("CATS-OLD-KEY", "ad_reward")

    assert not result.ok
    assert result.error == "license_expired"
    assert not cache_path.exists()


def test_heartbeat_success_updates_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "license_auth.json"
    cache = _cache(last_heartbeat_at="old")
    client = LicenseClient(
        cache_path=cache_path,
        transport=lambda *_: {
            "ok": True,
            "message": "心跳通过",
            "token_expires_at": "new-token-time",
            "expires_at": "new-expiry",
            "features": ["ad_reward"],
        },
    )

    result = client.heartbeat(cache)

    assert result.ok
    assert result.cache is not None
    assert result.cache.last_heartbeat_at != "old"
    assert load_license_cache(cache_path).token_expires_at == "new-token-time"


def test_heartbeat_failure_returns_error(tmp_path: Path) -> None:
    client = LicenseClient(
        cache_path=tmp_path / "license_auth.json",
        transport=lambda *_: {"ok": False, "error": "license_disabled", "message": "卡密已禁用"},
    )

    result = client.heartbeat(_cache())

    assert not result.ok
    assert result.error == "license_disabled"
    assert result.event == "license_heartbeat_failed"


def test_mask_license_key() -> None:
    assert mask_license_key("CATS-ABCD-EFGH-IJKL") == "CATS-ABCD-****"


def test_feature_permission_is_exact(tmp_path: Path) -> None:
    result = authorize_strategy(
        strategy="scrap_then_ad_reward",
        license_key="CATS-KEY",
        server_url="http://demo",
        client=LicenseClient(
            server_url="http://demo",
            cache_path=tmp_path / "license_auth.json",
            transport=lambda *_: {**_activate_ok(), "features": ["ad_reward"]},
        ),
    )

    assert not result.ok
    assert result.error == "feature_denied"


def test_server_url_is_configurable(tmp_path: Path) -> None:
    urls: list[str] = []
    client = LicenseClient(
        server_url="http://license.example.test/base/",
        cache_path=tmp_path / "license_auth.json",
        transport=lambda url, _payload: urls.append(url) or _activate_ok(),
    )

    client.activate("CATS-KEY", "ad_reward")

    assert urls == ["http://license.example.test/base/api/activate"]


def test_dev_bypass_requires_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CATS_LICENSE_DEV_BYPASS", raising=False)
    denied = authorize_strategy(
        strategy="ad_reward",
        license_key=None,
        server_url="http://demo",
        skip_for_dev=True,
    )
    monkeypatch.setenv("CATS_LICENSE_DEV_BYPASS", "1")
    allowed = authorize_strategy(
        strategy="ad_reward",
        license_key=None,
        server_url="http://demo",
        skip_for_dev=True,
    )

    assert not denied.ok
    assert allowed.ok and allowed.status == "dev_bypass"


def test_local_dev_license_keys_require_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = LicenseClient(cache_path=tmp_path / "license_auth.json")
    monkeypatch.delenv("CATS_LICENSE_DEV_BYPASS", raising=False)

    denied = client.activate("CATS-DEV-FULL-ACCESS", "scrap_then_ad_reward")
    monkeypatch.setenv("CATS_LICENSE_DEV_BYPASS", "1")
    allowed = client.activate("CATS-DEV-FULL-ACCESS", "scrap_then_ad_reward")
    heartbeat = client.heartbeat(allowed.cache)

    assert not denied.ok
    assert allowed.ok
    assert heartbeat.ok
    assert allowed.cache.features == (
        "ad_reward",
        "scrap_ad_battle",
        "scrap_then_ad_reward",
    )


def test_local_dev_license_features_are_restricted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CATS_LICENSE_DEV_BYPASS", "1")
    client = LicenseClient(cache_path=tmp_path / "license_auth.json")

    ad_only = client.activate("CATS-DEV-AD-ONLY", "ad_reward")
    denied = client.activate("CATS-DEV-AD-ONLY", "scrap_ad_battle")

    assert ad_only.ok
    assert not denied.ok and denied.error == "feature_denied"


def test_clear_license_cache(tmp_path: Path) -> None:
    path = tmp_path / "license_auth.json"
    path.write_text(json.dumps({}), encoding="utf-8")

    assert clear_license_cache(path)
    assert not path.exists()


def test_cli_without_license_is_rejected(tmp_path: Path) -> None:
    args = build_parser().parse_args(["--game", "cats", "--strategy", "ad_reward"])
    client = LicenseClient(cache_path=tmp_path / "missing.json")

    result, _ = authorize_strategy_run(args, tmp_path, client=client)

    assert not result.ok
    assert result.error == "license_cache_missing"


def test_cli_license_key_activates_requested_strategy(tmp_path: Path) -> None:
    args = build_parser().parse_args(
        [
            "--game",
            "cats",
            "--strategy",
            "scrap_then_ad_reward",
            "--license-key",
            "CATS-ABCD-EFGH",
        ]
    )
    client = LicenseClient(
        cache_path=tmp_path / "license.json",
        transport=lambda *_: _activate_ok(),
    )

    result, _ = authorize_strategy_run(args, tmp_path, client=client)

    assert result.ok
    assert result.event == "license_activate_ok"


def test_cli_dev_bypass_flag_requires_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = build_parser().parse_args(
        ["--game", "cats", "--strategy", "ad_reward", "--skip-license-check-for-dev"]
    )
    monkeypatch.delenv("CATS_LICENSE_DEV_BYPASS", raising=False)
    denied, _ = authorize_strategy_run(args, tmp_path)
    monkeypatch.setenv("CATS_LICENSE_DEV_BYPASS", "1")
    allowed, _ = authorize_strategy_run(args, tmp_path)

    assert not denied.ok
    assert allowed.ok


def _activate_ok() -> dict[str, object]:
    return {
        "ok": True,
        "message": "激活成功",
        "token": "secret-token",
        "token_expires_at": "2026-06-20T12:00:00+00:00",
        "expires_at": "2026-07-20T00:00:00+00:00",
        "features": ["ad_reward", "scrap_ad_battle", "scrap_then_ad_reward"],
        "device_limit": 1,
    }


def _cache(last_heartbeat_at: str = "") -> LicenseCache:
    return LicenseCache(
        "CATS-ABCD-EFGH",
        "device-hash",
        "secret-token",
        ("ad_reward", "scrap_ad_battle", "scrap_then_ad_reward"),
        "2026-07-20T00:00:00+00:00",
        "2026-06-20T12:00:00+00:00",
        "http://127.0.0.1:8000",
        last_heartbeat_at,
    )
