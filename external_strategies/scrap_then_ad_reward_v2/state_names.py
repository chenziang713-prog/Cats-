from __future__ import annotations


UNKNOWN_STATE = "UNKNOWN"

NORMALIZED_STATES = frozenset(
    {
        "HOME",
        "SCRAP_ENTRY_PAGE",
        "SCRAP_BATTLE_PAGE",
        "BATTLE_RUNNING_PAGE",
        "BATTLE_RESULT_PAGE",
        "SCRAP_WATCH_AD_PAGE",
        "AD_RUNNING_PAGE",
        "SPECIAL_CHEST_PAGE",
        "FILM_ENTRY_PAGE",
        "FILM_WATCH_PAGE",
        "REWARD_CONFIRM_PAGE",
        "ERROR_POPUP_PAGE",
        UNKNOWN_STATE,
    }
)

STATE_ALIASES = {
    "HOME_PAGE": "HOME",
    "ACTIVITY_PAGE": "SCRAP_ENTRY_PAGE",
    "TASK_PAGE": "SCRAP_BATTLE_PAGE",
    "AD_CLOSE_PAGE": "AD_RUNNING_PAGE",
    "REWARD_PAGE": "REWARD_CONFIRM_PAGE",
    "POPUP_PAGE": "ERROR_POPUP_PAGE",
    "UNKNOWN_PAGE": UNKNOWN_STATE,
}


def normalize_state_name(raw_state: str | None) -> tuple[str | None, str]:
    if raw_state is None:
        return None, UNKNOWN_STATE
    raw = str(raw_state).strip()
    if not raw:
        return raw, UNKNOWN_STATE
    return raw, STATE_ALIASES.get(raw, raw if raw in NORMALIZED_STATES else UNKNOWN_STATE)
