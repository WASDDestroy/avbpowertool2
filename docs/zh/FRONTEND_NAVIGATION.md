# 添加导航条目

如何在 TUI 导航树中添加新条目。

## 导航文件

所有导航定义在单个文件中：`avbpowertool/resources/navigation.json`。

## 结构

```json
{
  "schema_version": 1,
  "start_route": "route:home",
  "routes": { ... },
  "actions": { ... }
}
```

- **routes**：导航树中的页面。每个页面的 items 要么是 action，要么是子路由。
- **actions**：每个可调用 action 的元数据（标签 key、描述 key）。

## 在现有路由中添加 Action

1. 在 `actions` 部分添加 action 元数据：

```json
"action:my.new_action": {
  "label_key": "my.new_action.label",
  "description_key": "my.new_action.description"
}
```

2. 在路由的 `items` 数组中添加 action 条目：

```json
"route:home": {
  "items": [
    {"action": "action:my.new_action", "shortcut": "N"},
    ...
  ]
}
```

3. 在 `locale/en/LC_MESSAGES/avbpowertool.po` 和 `locale/zh/LC_MESSAGES/avbpowertool.po` 中添加翻译。

4. 在 `presentation/tui/app.py:_dispatch_action()` 中注册 action 处理器：

```python
view_map = {
    ...
    "action:my.new_action": my_view.show,
}
```

5. 在 `presentation/tui/views/my_view.py` 中创建视图模块。

## 添加新的子路由

1. 在 `routes` 部分添加路由：

```json
"route:my_section": {
  "title_key": "my.section.title",
  "description_key": "my.section.description",
  "parent": "route:home",
  "items": [
    {"action": "action:my.action1", "shortcut": "A"},
    {"action": "action:my.action2", "shortcut": "B"}
  ]
}
```

2. 在父路由中添加路由条目：

```json
"route:home": {
  "items": [
    {"route": "route:my_section", "shortcut": "M"},
    ...
  ]
}
```

3. 将所有引用的 action 添加到 `actions` 部分。

## 规则

- **快捷键**必须是单个大写字母，在每个路由内唯一。
- **Action ID** 使用 `action:<domain>.<verb>` 格式（如 `action:image.sign`）。
- **Route ID** 使用 `route:<name>` 格式（如 `route:config_manager`）。
- 路由器会自动添加 `[B] 返回`（非根路由时）和 `[E] 退出`（根路由时）。
- items 中引用的每个 action 和 route 必须存在于各自的部分中。
- 契约测试 `tests/contract/test_navigation_schema.py` 验证这些规则。

## 验证

修改 `navigation.json` 后，运行契约测试：

```shell
uv run pytest tests/contract/test_navigation_schema.py -v
```

这会检查：
- 所有 action 引用存在于 `actions` 部分
- 所有 route 引用存在于 `routes` 部分
- 没有孤立路由（每个路由都可从起点到达）
- 快捷键在每个路由内唯一
