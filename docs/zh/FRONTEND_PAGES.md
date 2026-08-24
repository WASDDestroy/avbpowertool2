# 编辑和创建 TUI 页面

如何创建或修改 TUI 视图（页面）。

## 视图架构

每个 TUI 页面是 `avbpowertool/presentation/tui/views/` 中的一个 Python 模块，包含一个 `show()` 函数：

```python
def show(stdscr: curses.window, ws: WorkspacePaths, avb: AvbToolPort) -> None
```

- `stdscr` — 用于渲染的 curses 窗口
- `ws` — 工作区路径（不可变）
- `avb` — avbtool 端口（用于子进程调用）

## 创建新视图

1. 在 `avbpowertool/presentation/tui/views/my_view.py` 中创建文件：

```python
"""我的自定义视图。"""

from __future__ import annotations

import curses

from avbpowertool.application.ports import AvbToolPort
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths
from avbpowertool.presentation.tui.widgets import (
    SelectorWidget,
    confirm_dialog,
    message_screen,
)


def show(stdscr: object, ws: WorkspacePaths, avb: AvbToolPort) -> None:
    """我的自定义视图。"""
    stdscr_c: curses.window = stdscr  # type: ignore[assignment]

    # 你的逻辑
    lines = ["你好，这是我的自定义视图！"]
    message_screen(stdscr_c, "我的视图", lines)
```

2. 在 `presentation/tui/app.py:_dispatch_action()` 中注册：

```python
from avbpowertool.presentation.tui.views import my_view

view_map = {
    ...
    "action:my.action": my_view.show,
}
```

3. 在 `resources/navigation.json` 中添加 action。

4. 在 `.po` 文件中添加翻译。

## 可用组件

### SelectorWidget

带键盘导航的单选/多选列表。

```python
from avbpowertool.presentation.tui.widgets import SelectorWidget

# 单选
sel = SelectorWidget("选择一个选项", ["选项 A", "选项 B", "选项 C"])
result = sel.run(stdscr)  # 返回选中索引列表，如 [0]
if result:
    chosen_index = result[0]

# 多选
sel = SelectorWidget("选择项目", items, multi_select=True)
result = sel.run(stdscr)  # 返回选中索引列表，如 [0, 2]
```

**键盘控制：**
- 上/下 或 k/j：导航
- Enter：确认选择
- Space：切换选择（多选模式）
- Esc：取消

### confirm_dialog

是/否确认对话框。

```python
from avbpowertool.presentation.tui.widgets import confirm_dialog

if confirm_dialog(stdscr, "确定吗？"):
    # 继续
    pass
```

### message_screen

显示带标题的消息屏幕。等待 Enter 或 Esc。

```python
from avbpowertool.presentation.tui.widgets import message_screen

message_screen(stdscr, "结果", [
    "第 1 行",
    "第 2 行",
    "第 3 行",
])
```

### input_prompt

文本输入提示。

```python
from avbpowertool.presentation.tui.widgets import input_prompt

name = input_prompt(stdscr, "输入配置名称：")
```

## 从视图调用用例

视图调用应用层用例并显示结果。永远不要直接访问基础设施层。

```python
from avbpowertool.application.commands import InspectImagesRequest
from avbpowertool.application.services.inspect_images import InspectImagesUseCase

def show(stdscr, ws, avb):
    uc = InspectImagesUseCase(ws, avb)
    result = uc.execute(InspectImagesRequest(image_names=("boot",)))

    lines = []
    for img in result.images:
        lines.append(f"{img.image_name}: {img.descriptor}")
    for iss in result.issues:
        lines.append(f"[{iss.error_code}] {iss.message}")

    message_screen(stdscr, "结果", lines)
```

## 获取活动 Profile

```python
from avbpowertool.infrastructure.persistence.profile_repository import ProfileRepository

repo = ProfileRepository(ws)
active_id = repo.get_active_profile_id() or "current"
```

## 列出 Profile 中的镜像

```python
profile_dir = ws.resolve_profile_dir(active_id)
images = [f.stem for f in sorted(profile_dir.iterdir()) if f.suffix == ".img"]
```

## 模式

### 选择-执行模式

```python
def show(stdscr, ws, avb):
    # 1. 构建列表
    items = ["boot", "system", "vbmeta"]

    # 2. 显示选择器
    sel = SelectorWidget("选择镜像", items, multi_select=True)
    chosen = sel.run(stdscr)
    if not chosen:
        return  # 用户取消

    # 3. 确认
    if not confirm_dialog(stdscr, "继续吗？"):
        return

    # 4. 执行
    selected = [items[i] for i in chosen]
    # ... 调用用例 ...

    # 5. 显示结果
    message_screen(stdscr, "完成", [f"已处理 {len(selected)} 个项目"])
```

### 错误处理

```python
def show(stdscr, ws, avb):
    try:
        # ... 调用用例 ...
        pass
    except Exception as exc:
        message_screen(stdscr, "错误", [str(exc)])
        return
```
