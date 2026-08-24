# AVBPowerTool2 实现计划

> 详细版本请参阅 [英文版](../en/IMPLEMENTATION_PLAN.md)。

## 1. 决策记录

| 决策 | 选择 | 理由 |
|---|---|---|
| 起点 | 从头开始 | 干净的代码，无遗留债务 |
| avbtool 调用 | 仅 subprocess | avbtool 仅暴露 CLI 接口 |
| avbtool FEC 补丁 | 最小补丁 (A2) | 当外部 `fec` 不可用时回退到 Python FEC |
| FEC 调用路径 | avbtool 内部调用补丁后的 FEC (E1) | avbtool 端到端控制签名流程 |
| TUI 框架 | curses + windows-curses | POSIX 上为标准库；Windows 上为单个可选依赖 |
| 导航 | 单个 navigation.json | 易于验证、编辑、对比 |
| 配置 Schema | v2 + keys.json 映射 | 规范字段名，显式 schema 版本 |
| 密钥库布局 | `profiles/<name>/keys/` + `manifest.json` | 一个 Profile = 一个密钥库 |
| 包名 / CLI | `avbpowertool` / `avbpowertool` | |
| Python 版本 | 3.11+ | match/case、X\|Y 联合语法、完整 gettext |
| 国际化 | Python gettext (.po/.mo) | 标准库，标准工具链 |
| 日志 | Python logging 标准库 | 不自造单例 |
| 测试 | 全新编写 | 老测试有结构性问题 |
| 签名执行 | staging + 原子替换 | 原始镜像在验证前不受影响 |
| 归档格式 | 新格式带 manifest | 不兼容 v1 |
| 范围 | Phase 6 完成 | CLI + TUI + 所有核心用例 |

## 2. 目标目录结构

```
AVBPowerTool2/
  avbtool.py                          # 内置 AOSP avbtool，最小补丁支持 FEC
  pyproject.toml                       # 构建配置、依赖、入口点

  avbpowertool/                        # Python 包
    domain/                            # 纯逻辑，无 I/O
    application/                       # 用例、端口、事件
    infrastructure/                    # I/O 适配器
    presentation/                      # CLI 和 TUI
    resources/                         # 导航配置
    locale/                            # gettext 翻译
    vendor/                            # 内置 FEC 编码器
    bootstrap.py                       # 组合根
    _version.py                        # 版本字符串

  tests/                               # 测试
  docs/en/                             # 英文文档
  docs/zh/                             # 中文文档
```

## 3. 实现阶段

### Phase 0：项目骨架
- pyproject.toml、包骨架、avbtool FEC 补丁、测试基础设施
- **0.5 天**

### Phase 1：领域层
- 模型、错误、验证、签名计划、依赖图
- **1 天**

### Phase 2：基础设施 — avbtool 适配器
- 端口协议、SubprocessAvbTool、输出解析器、命令构建器
- **1 天**

### Phase 3：基础设施 — 文件系统与配置
- 工作区、原子写入器、Profile 编解码、Profile/密钥/归档仓库
- **1.5 天**

### Phase 4：应用层
- 命令/结果类型、进度事件、7 个用例
- **1.5 天**

### Phase 5：CLI
- ActionId、argparse 解析器、处理器、渲染器、退出码
- **1 天**

### Phase 6：TUI
- 导航、路由器、组件、应用、视图、国际化、组合根
- **2 天**

**总计：约 8.5 天**

## 4. 质量门禁

每个阶段必须通过：

1. `pytest` — 全部测试通过
2. `ruff check` — 零警告
3. `ruff format` — 全部文件已格式化
4. `pyright` — 零错误（strict 模式）
5. 导航 schema 契约测试（Phase 6）
6. 国际化完整性检查（Phase 6）
