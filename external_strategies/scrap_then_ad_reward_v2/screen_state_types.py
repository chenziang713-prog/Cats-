from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MarkerMatchResult:
    """单个模板标志的匹配结果。

    marker_name 是模板标志名；matched 表示是否命中；confidence 是匹配置信度；
    center/template_path 保留给调试和后续真实模板匹配使用。
    """

    marker_name: str
    matched: bool
    confidence: float = 0.0
    center: tuple[int, int] | None = None
    template_path: str | None = None


@dataclass(frozen=True)
class ScreenStateTemplate:
    """某个界面的识别规则。

    required_any 表示命中任意一个即可；required_all 表示必须全部命中；
    exclude_any 表示一旦命中就排除该状态；priority 用来解决多个状态同时命中。
    """

    state_name: str
    required_any: list[str] = field(default_factory=list)
    required_all: list[str] = field(default_factory=list)
    exclude_any: list[str] = field(default_factory=list)
    threshold: float = 0.80
    priority: int = 0
    description: str = ""
    template_dirs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ScreenStateResult:
    """当前界面识别结果。

    这个结构只描述“当前画面像哪个界面”，不包含点击、返回、等待等执行动作。
    """

    state_name: str
    matched: bool
    confidence: float
    priority: int
    matched_markers: list[str] = field(default_factory=list)
    missing_markers: list[str] = field(default_factory=list)
    excluded_markers: list[str] = field(default_factory=list)
    best_marker: str | None = None
    reason: str = ""
    raw_scores: dict[str, float] = field(default_factory=dict)
    screenshot_path: str | None = None
