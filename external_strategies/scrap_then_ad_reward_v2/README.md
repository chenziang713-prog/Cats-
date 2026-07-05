# 废铁 + 胶卷广告 v2 状态识别层

本目录放第一阶段新增的“界面状态识别层”。第一阶段只做“当前界面识别”，不接管真实点击，不修改旧 runner，不替换现有正式执行流程。

第二阶段才会接入“flow_state + screen_state -> action”的流程控制。

## 文件职责

- `screen_state_types.py`：定义 `ScreenStateResult`、`ScreenStateTemplate`、`MarkerMatchResult`。
- `screen_state_templates.py`：集中配置 HOME、SCRAP_BATTLE_PAGE、AD_RUNNING_PAGE 等状态模板。
- `screen_state_detector.py`：统一状态检测入口，优先复用现有 detections。
- `state_action_templates.py`：每个状态对应的动作模板函数，当前全部返回 `no_action`。
- `strategy.py`：很薄的 v2 调试入口，负责调用状态识别和动作模板。
- `__init__.py`：Python 包导入入口。

## 如何新增一个状态

1. 在 `screen_state_templates.py` 中新增一个 `_state(...)` 配置。
2. 填写 `required_any`、`required_all`、`exclude_any`、`threshold`、`priority`、`description`。
3. 把新状态加入 `SCREEN_STATE_TEMPLATES` 列表。
4. 在 `state_action_templates.py` 中新增对应的 `handle_xxx_state(...)` 模板函数。
5. 把新函数加入 `STATE_ACTION_HANDLERS`。

## 如何添加模板图片

状态模板里先写模板名，例如 `battle_button`。检测器会按模板名寻找 `battle_button.png`。

当前预留目录包括：

- `external_strategies/scrap_then_ad_reward_v2/templates`
- `external_strategies/scrap_then_ad_reward/templates`
- `external_strategies/scrap_ad_battle/templates`

模板图片暂时不存在也没关系，检测器会安全跳过，不会报错。

## 如何修改状态优先级

在 `screen_state_templates.py` 修改对应状态的 `priority`。多个状态同时命中时，先比较 `priority`，优先级相同再比较 `confidence`。

## 如何查看当前识别结果

优先调用：

```python
from external_strategies.scrap_then_ad_reward_v2.strategy import debug_detect_screen_state

result = debug_detect_screen_state(context, context.detections)
print(result["explanation"])
```

底层检测函数是：

```python
detect_current_screen_state_from_detections(detections)
```

## 后续如何接入流程控制层

后续流程控制应走：

```text
screen_state_detector -> state_action_templates -> flow_state + screen_state -> action
```

`screen_state` 是“眼睛”，只判断画面；`flow_state` 是“流程记忆”，判断当前允许做什么。同一个画面在不同流程阶段可能需要完全不同的动作。
