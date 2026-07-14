from __future__ import annotations

from pathlib import Path

from external_strategies.scrap_then_ad_reward_v2.film_flow import FILM_STEPS
from external_strategies.scrap_then_ad_reward_v2.marker_groups import REGISTERED_MARKERS
from external_strategies.scrap_then_ad_reward_v2.screen_state_detector import (
    _marker_matches,
    _template_paths_for_marker,
    detect_current_screen_state_from_detections,
)
from external_strategies.scrap_then_ad_reward_v2.screen_state_templates import (
    DEFAULT_TEMPLATE_DIRS,
    DISABLED_SCREEN_STATE_TEMPLATES,
    SCREEN_STATE_TEMPLATES,
)
from external_strategies.scrap_then_ad_reward_v2.state_names import STATE_ALIASES
from external_strategies.scrap_then_ad_reward_v2.validation import validate_strategy_config


ROOT = Path(__file__).resolve().parents[1]
TEAMMATE_DIR = ROOT / "状态判断文件及状态图片"


def test_official_screen_state_templates_import_and_registry_is_consistent() -> None:
    assert SCREEN_STATE_TEMPLATES
    assert all(key == template.state_name for key, template in SCREEN_STATE_TEMPLATES.items())
    assert len(SCREEN_STATE_TEMPLATES) == len({template.state_name for template in SCREEN_STATE_TEMPLATES.values()})


def test_teammate_original_delivery_directory_is_preserved() -> None:
    assert (TEAMMATE_DIR / "screen_state_templates.py").is_file()
    assert (TEAMMATE_DIR / "page_status_judge_page").is_dir()
    assert (TEAMMATE_DIR / "user_templates").is_dir()


def test_template_dirs_include_teammate_assets_by_relative_path() -> None:
    assert "../../状态判断文件及状态图片/user_templates" in DEFAULT_TEMPLATE_DIRS
    assert "../../状态判断文件及状态图片/page_status_judge_page" in DEFAULT_TEMPLATE_DIRS
    assert not any(str(ROOT) in directory for directory in DEFAULT_TEMPLATE_DIRS)


def test_marker_loader_finds_teammate_marker_subdirectories() -> None:
    assert _template_paths_for_marker("home_marker", "../../状态判断文件及状态图片/page_status_judge_page")
    assert _template_paths_for_marker("close_buttons", "../../状态判断文件及状态图片/user_templates")
    assert _template_paths_for_marker(
        "tournament_watch_battle_marker",
        "../../状态判断文件及状态图片/page_status_judge_page",
    )


def test_registry_references_only_registered_markers_for_enabled_states() -> None:
    report = validate_strategy_config(
        states=SCREEN_STATE_TEMPLATES,
        flow_rules=(),
        registered_markers=REGISTERED_MARKERS,
        supported_actions=("wait", "no_action", "press_back", "tap_marker"),
        known_steps=(),
        aliases={},
        tap_marker_allow_list=(),
    )

    assert report.errors == []


def test_missing_marker_is_reported_by_validation() -> None:
    bad = next(iter(SCREEN_STATE_TEMPLATES.values()))
    bad = type(bad)(
        state_name="BAD_MISSING_MARKER",
        required_any=["marker_that_was_not_delivered"],
        threshold=0.8,
        priority=1,
        description="bad",
    )

    report = validate_strategy_config(
        states=[bad],
        registered_markers=REGISTERED_MARKERS,
    )

    assert any("not registered" in error.message for error in report.errors)


def test_wildcard_rules_match_existing_detector_capability() -> None:
    result = detect_current_screen_state_from_detections(
        {"close_user_2_1": {"confidence": 0.91}}
    )

    assert _marker_matches("close_user_*", "close_user_2_1")
    assert result.state_name == "AD_RUNNING_PAGE"


def test_home_right_ad_page_does_not_steal_plain_home() -> None:
    result = detect_current_screen_state_from_detections(
        {
            "home_marker": {"confidence": 0.91},
            "underground_park_entrance_buttons": {"confidence": 0.92},
        }
    )

    assert result.state_name == "HOME"
    assert "HOME_RIGHT_AD_PAGE" not in SCREEN_STATE_TEMPLATES
    assert "HOME_RIGHT_AD_PAGE" in DISABLED_SCREEN_STATE_TEMPLATES


def test_ad_running_page_requires_explicit_close_marker() -> None:
    assert detect_current_screen_state_from_detections({}).state_name == "UNKNOWN"
    result = detect_current_screen_state_from_detections({"close_buttons": {"confidence": 0.93}})

    assert result.state_name == "AD_RUNNING_PAGE"
    assert "close_buttons" in result.matched_markers


def test_teammate_state_names_are_preserved_not_renamed() -> None:
    assert "GET_THREE_BOLTS_MARKER" in DISABLED_SCREEN_STATE_TEMPLATES
    assert "BATTLE_RUNNING_PAGE" in SCREEN_STATE_TEMPLATES
    assert "TOURNAMENT_PAGE" in DISABLED_SCREEN_STATE_TEMPLATES
    assert "TOURNAMENT_WATCH_BATTLE_PAGE" not in SCREEN_STATE_TEMPLATES
    assert "TOURNAMENT_ADVANCE_FAILED_PAGE" not in SCREEN_STATE_TEMPLATES


def test_teammate_marker_directory_names_are_preserved() -> None:
    marker_dirs = {
        path.name
        for path in (TEAMMATE_DIR / "page_status_judge_page").rglob("*")
        if path.is_dir()
    } | {
        path.name
        for path in (TEAMMATE_DIR / "user_templates").iterdir()
        if path.is_dir()
    }

    for marker_name in (
        "tank_attack_marke",
        "home_marker",
        "underground_park_entrance_buttons",
        "home_right_ad_buttons",
        "right_ad_reward_success_marker",
        "close_buttons",
        "claim_buttons",
        "confirm_buttons",
    ):
        assert marker_name in marker_dirs


def test_film_flow_steps_and_state_aliases_are_not_rewritten_for_teammate_import() -> None:
    assert "ENTER_FILM" in FILM_STEPS
    assert STATE_ALIASES["HOME_PAGE"] == "HOME"
    assert STATE_ALIASES["AD_CLOSE_PAGE"] == "AD_RUNNING_PAGE"
    assert "FILM_WATCH_PAGE" not in STATE_ALIASES
    assert "RIGHT_AD_REWARD_SUCCESS_PAGE" not in STATE_ALIASES


def test_no_adb_or_click_allow_list_change_is_needed() -> None:
    from cats_automatic.actions import DEFAULT_TAP_MARKER_ALLOW_LIST

    assert "close_buttons" not in DEFAULT_TAP_MARKER_ALLOW_LIST
    assert "home_right_ad_buttons" not in DEFAULT_TAP_MARKER_ALLOW_LIST
