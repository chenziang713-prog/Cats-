from __future__ import annotations


UNKNOWN_STATE = "UNKNOWN"

NORMALIZED_STATES = frozenset(
    {
        "HOME",
        "FILM_WATCH_PAGE",
        "AD_CLOSE_PAGE",
        "RIGHT_AD_REWARD_SUCCESS_PAGE",
        "ERROR_POPUP_PAGE",
        UNKNOWN_STATE,
    }
)

STATE_ALIASES = {
    "HOME_PAGE": "HOME",
    "POPUP_PAGE": "ERROR_POPUP_PAGE",
    "UNKNOWN_PAGE": UNKNOWN_STATE,
    "REWARD_PAGE": "RIGHT_AD_REWARD_SUCCESS_PAGE",
}


def normalize_state_name(raw_state: str | None) -> tuple[str | None, str]:
    if raw_state is None:
        return None, UNKNOWN_STATE
    raw = str(raw_state).strip()
    if not raw:
        return raw, UNKNOWN_STATE
    return raw, STATE_ALIASES.get(raw, raw if raw in NORMALIZED_STATES else UNKNOWN_STATE)
