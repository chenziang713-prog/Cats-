from __future__ import annotations

from collections.abc import Sequence

from .strategies.ad_reward import Strategy


def close_button_template_names() -> Sequence[str]:
    return (
        "ad-close-x.png",
        "ad-close-text.png",
        "ad-skip.png",
        "ad-skip-light.png",
    )


def create_strategy() -> Strategy:
    return Strategy()
