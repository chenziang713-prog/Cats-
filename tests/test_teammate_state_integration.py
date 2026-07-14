from __future__ import annotations

from pathlib import Path

from external_strategies.scrap_then_ad_reward_v2.film_flow import FILM_STATES, FILM_STEPS
from external_strategies.scrap_then_ad_reward_v2.marker_groups import AD_CLOSE_MARKERS, REGISTERED_MARKERS
from external_strategies.scrap_then_ad_reward_v2.screen_state_detector import (
    _template_paths_for_marker,
    detect_current_screen_state_from_detections,
)
from external_strategies.scrap_then_ad_reward_v2.screen_state_templates import (
    ACTION_ONLY_MARKERS,
    ACTIVE_STATE_NAMES,
    DEFAULT_TEMPLATE_DIRS,
    DISABLED_SCREEN_STATE_TEMPLATES,
    SCREEN_STATE_TEMPLATES,
)
from external_strategies.scrap_then_ad_reward_v2.state_names import STATE_ALIASES
from external_strategies.scrap_then_ad_reward_v2.template_sources import (
    V2_CANONICAL_TEMPLATE_DIRS,
    collect_canonical_marker_names,
    marker_name_for_template_path,
)
from external_strategies.scrap_then_ad_reward_v2.validation import validate_strategy_config
from tools.debug_screen_state_v2 import analyze_image, template_search_dirs


ROOT = Path(__file__).resolve().parents[1]
TEAMMATE_DIR = ROOT / "状态判断文件及状态图片"
TEST_MODES = ROOT / "test modes"


def test_official_registry_is_active_only() -> None:
    assert SCREEN_STATE_TEMPLATES
    assert set(SCREEN_STATE_TEMPLATES) <= set(ACTIVE_STATE_NAMES)
    assert "FILM_ENTRY_PAGE" not in SCREEN_STATE_TEMPLATES
    assert "AD_RUNNING_PAGE" not in SCREEN_STATE_TEMPLATES
    assert "REWARD_CONFIRM_PAGE" not in SCREEN_STATE_TEMPLATES


def test_disabled_legacy_states_are_documented_not_registered() -> None:
    for state_name in ("FILM_ENTRY_PAGE", "AD_RUNNING_PAGE", "REWARD_CONFIRM_PAGE"):
        assert state_name in DISABLED_SCREEN_STATE_TEMPLATES
        assert state_name not in SCREEN_STATE_TEMPLATES


def test_teammate_original_delivery_directory_is_preserved() -> None:
    assert (TEAMMATE_DIR / "screen_state_templates.py").is_file()
    assert (TEAMMATE_DIR / "page_status_judge_page").is_dir()
    assert (TEAMMATE_DIR / "user_templates").is_dir()


def test_v2_template_dirs_are_canonical_only() -> None:
    expected = [str(path) for path in V2_CANONICAL_TEMPLATE_DIRS]
    assert [str(path) for path in template_search_dirs()] == expected
    assert DEFAULT_TEMPLATE_DIRS == [
        "templates/page_status_judge_page",
        "templates/user_templates",
    ]
    forbidden = (
        "scrap_ad_battle/templates",
        "scrap_then_ad_reward/templates",
        "src/cats_automatic/games/cats/templates",
        "状态判断文件及状态图片",
    )
    joined = "\n".join(expected)
    for text in forbidden:
        assert text not in joined


def test_marker_loader_finds_only_canonical_marker_subdirectories() -> None:
    home_paths = _template_paths_for_marker("home_marker", "templates/page_status_judge_page")
    close_paths = _template_paths_for_marker("close_buttons", "templates/user_templates")
    assert home_paths
    assert close_paths
    assert all("scrap_then_ad_reward_v2" in str(path) for path in [*home_paths, *close_paths])
    assert _template_paths_for_marker("home_marker", "../../状态判断文件及状态图片/page_status_judge_page") == []


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


def test_action_only_markers_are_not_state_markers() -> None:
    assert ACTION_ONLY_MARKERS == frozenset(
        {"ad_entry", "error_buttons", "retry_buttons", "reconnect_buttons"}
    )
    for template in SCREEN_STATE_TEMPLATES.values():
        required = set(template.required_any) | set(template.required_all)
        assert required.isdisjoint(ACTION_ONLY_MARKERS)


def test_ad_entry_can_coexist_with_home_without_creating_film_entry_state() -> None:
    result = detect_current_screen_state_from_detections(
        {"main-definate": {"confidence": 0.91}, "ad_entry": {"confidence": 0.90}}
    )

    assert result.state_name == "HOME"
    assert "FILM_ENTRY_PAGE" not in SCREEN_STATE_TEMPLATES


def test_ad_close_page_requires_explicit_close_marker() -> None:
    assert detect_current_screen_state_from_detections({}).state_name == "UNKNOWN"
    result = detect_current_screen_state_from_detections(
        {"close_buttons": _close_button_detection(0.93)}
    )

    assert result.state_name == "AD_CLOSE_PAGE"
    assert "close_buttons" in result.matched_markers
    assert AD_CLOSE_MARKERS == ("close_buttons", "close_ad", "close_user_*", "close_end_*")


def test_reward_success_beats_weak_close_marker_by_exclusion_not_priority_only() -> None:
    result = detect_current_screen_state_from_detections(
        {
            "right_ad_reward_success_buttons": {"confidence": 0.93},
            "right_ad_reward_success_marker": {"confidence": 0.94},
            "close_buttons": _close_button_detection(0.82),
        }
    )

    assert result.state_name == "RIGHT_AD_REWARD_SUCCESS_PAGE"
    assert result.selection_reason == "single_active_state_match"


def test_state_conflict_returns_unknown() -> None:
    result = detect_current_screen_state_from_detections(
        {
            "main-definate": {"confidence": 0.91},
            "watch_ad_film": {"confidence": 0.91},
        }
    )

    assert result.state_name == "UNKNOWN"
    assert result.selection_reason == "state_conflict"
    assert {item["state"] for item in result.candidate_states} == {"HOME", "FILM_WATCH_PAGE"}


def test_nested_template_marker_names_do_not_use_screenshot_stems() -> None:
    marker_names = collect_canonical_marker_names()

    assert "ad_entry" in marker_names
    assert "main-definate" in marker_names
    assert not any(name.startswith("screenshot_") for name in marker_names)


def test_marker_name_comes_from_marker_folder() -> None:
    path = next(_template_paths_for_marker("home_marker", "templates/page_status_judge_page").__iter__())
    assert marker_name_for_template_path(path, V2_CANONICAL_TEMPLATE_DIRS[0]) == "home_marker"


def test_real_home_screenshots_are_home_and_ad_entry_can_be_detected() -> None:
    for screenshot in sorted((TEST_MODES / "1.game_home_page").glob("*.png")):
        record = analyze_image(screenshot)
        assert record["screen_state"] == "HOME"
        assert record["screen_state"] != "FILM_ENTRY_PAGE"
    adb_home = analyze_image(TEST_MODES / "1.game_home_page" / "adb_home.png")
    assert adb_home["screen_state"] == "HOME"
    assert "ad_entry" in adb_home["generated_detections"]


def test_real_ad_playing_without_close_is_unknown() -> None:
    record = analyze_image(TEST_MODES / "4.ad_playing_page" / "123 (1).png")
    assert record["screen_state"] == "UNKNOWN"


def test_real_close_button_image_is_ad_close_page() -> None:
    record = analyze_image(TEST_MODES / "5.ad_close_button_page" / "close_buttons" / "2 (1).png")
    assert record["screen_state"] == "AD_CLOSE_PAGE"


def test_real_reward_success_page_is_not_stolen_by_close_page() -> None:
    record = analyze_image(TEST_MODES / "6.ad_reward_page" / "4ff3a65555b4fb3d657a180ba322a8c6.png")
    assert record["screen_state"] == "RIGHT_AD_REWARD_SUCCESS_PAGE"


def test_real_adb_reward_confirm_is_reward_not_error_popup() -> None:
    record = analyze_image(TEST_MODES / "6.ad_reward_page" / "adb_reward_confirm.png")

    assert record["generated_detections"]["error_buttons"]["confidence"] >= 0.95
    assert record["generated_detections"]["error_popups"]["confidence"] < 0.80
    assert record["screen_state"] == "RIGHT_AD_REWARD_SUCCESS_PAGE"
    assert record["selected_state"] == "RIGHT_AD_REWARD_SUCCESS_PAGE"
    assert record["selected_state"] != "ERROR_POPUP_PAGE"
    assert "get_reward" in record["matched_markers"]


def test_film_flow_steps_and_state_aliases_use_current_state_names() -> None:
    assert "ENTER_FILM" in FILM_STEPS
    assert "FILM_WATCH_PAGE" in FILM_STATES
    assert "AD_RUNNING_PAGE" not in FILM_STATES
    assert STATE_ALIASES["HOME_PAGE"] == "HOME"
    assert "AD_CLOSE_PAGE" not in STATE_ALIASES
    assert STATE_ALIASES["REWARD_PAGE"] == "RIGHT_AD_REWARD_SUCCESS_PAGE"


def _close_button_detection(confidence: float) -> dict[str, object]:
    return {
        "confidence": confidence,
        "center": (100, 40),
        "template_path": str(_template_paths_for_marker("close_buttons")[0]),
    }
