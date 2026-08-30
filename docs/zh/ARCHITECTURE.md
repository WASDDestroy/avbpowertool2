# 架构文档

AVBPowerTool2 的整体架构：分层、数据流，以及各模块的职责。

## 总览

AVBPowerTool2 是 AOSP `avbtool.py` 的配置驱动封装，采用**四层六边形（端口与适配器）架构**：

```
                        ┌─────────────────────────────┐
                        │      presentation/          │
                        │  cli/ (argparse)  tui/ (curses) │
                        │  actions.py  audit.py  i18n.py  │
                        └──────────────┬──────────────┘
                                       │ 只调用用例
                        ┌──────────────▼──────────────┐
                        │      application/           │
                        │  commands.py (请求/结果)      │
                        │  ports.py    (Protocol)      │
                        │  services/   (用例)          │
                        └──────────────┬──────────────┘
                                       │ 只依赖 domain
                        ┌──────────────▼──────────────┐
                        │        domain/              │
                        │  models  validation          │
                        │  signing_plan  dependency_graph │
                        │  command_spec  command_builder  │
                        │  errors                       │
                        └─────────────────────────────┘
                                       ▲ 实现端口
                        ┌──────────────┴──────────────┐
                        │      infrastructure/        │
                        │  avbtool/   (子进程 runner、解析器) │
                        │  filesystem/ (workspace、原子写入) │
                        │  persistence/ (profile/key/archive/settings) │
                        └─────────────────────────────┘
```

依赖方向**严格向内**：presentation → application → domain。Infrastructure 位于外侧，实现 `application/ports.py` 中定义的端口（接口）。两条硬性规则：

- `domain/` 不 import 其他任何层。
- `application/` 只依赖 domain 对象和 `ports.py` 中的 `Protocol` 定义——绝不依赖具体的 infrastructure 类。

## 各层职责

### domain/ — 纯业务逻辑，零 I/O

所有模型都是 `@dataclass(frozen=True)`。该层任何地方都不允许文件、网络或子进程访问。

| 模块 | 职责 |
|---|---|
| `models.py` | 核心数据类：`AvbProfile`、`PartitionConfig`、`SigningStep`、`SigningPlan`、`ChainDescriptor`、`ImageInspection`、`OperationIssue` |
| `validation.py` | Profile / 分区 / 密钥 manifest 校验器（返回 issue 列表，不针对用户数据抛异常） |
| `signing_plan.py` | `SigningPlanBuilder` —— 将 profile + 镜像转化为有序的 `SigningPlan`（由 `SigningStep` 组成）。纯规划器：只计算，不写任何东西 |
| `dependency_graph.py` | vbmeta 链的拓扑排序，保证链式分区在其依赖之后签名 |
| `command_spec.py` | `CommandSpec` —— 每条 avbtool 命令参数的声明式描述（用于校验与默认值） |
| `command_builder.py` | 从 `PartitionConfig` 构建 avbtool 参数列表（`build_hash_footer_command`、`build_vbmeta_command` 等） |
| `errors.py` | 带稳定错误码的领域异常（`config.key_missing`、`image.not_found`、`signing.step_failed`、`workspace.root_not_found` 等） |

注意 `command_builder.py` 位于 domain 而非 infrastructure：命令构建是纯业务关注点（只有当选项值与默认值不同时才输出该选项）。`infrastructure/avbtool/command_builder.py` 只是它的向后兼容 re-export。

### application/ — 用例与端口

| 模块 | 职责 |
|---|---|
| `commands.py` | 每个用例的冻结 `*Request` / `*Result` 数据类（`SignImagesRequest`、`InspectImagesResult` 等）。这是 presentation 与 application 之间的 API 面 |
| `ports.py` | `AvbToolPort`（如何调用 avbtool 操作）与 `ProgressSink`（进度事件：`StepStarted`、`StepCompleted`、`SigningCompleted`）。均为 Protocol——用例接受任何实现 |
| `services/` | 每个能力一个模块：`inspect_images.py`、`sign_images.py`、`manage_configs.py`、`manage_profiles.py`、`manage_keys.py`、`resolve_chains.py` |

用例模式：构造函数接收所需端口（及仓储），`execute(request) -> result` 负责编排。用例围绕领域逻辑处理事务/日志，但绝不直接触碰文件系统或子进程——一律经由端口。

签名调用的数据流示例：

```
SignImagesUseCase.execute(SignImagesRequest)
  -> SigningPlanBuilder (domain)        # 纯规划：排序步骤、暂存副本
  -> AvbToolPort (infrastructure)       # 逐条执行 avbtool 命令
  -> ProgressSink (presentation)        # 上报步骤进度
  -> SignImagesResult(steps, issues)
```

### infrastructure/ — I/O 适配器

| 模块 | 职责 |
|---|---|
| `avbtool/runner.py` | `SubprocessAvbTool` —— 通过子进程调用内嵌 `avbtool.py` 实现 `AvbToolPort`。avbtool 是 vendor 代码：只能以子进程方式调用，绝不 import 其内部 |
| `avbtool/output_parser.py` | `parse_info_image` —— 将 `avbtool info_image` 文本输出解析为 `ImageInspection` 领域对象 |
| `filesystem/workspace.py` | `WorkspacePaths` —— 冻结数据类，解析规范目录布局（`Images/`、`profiles/`、`Logs/`、`.avbpowertool-staging/`、`avbtool.py`）。所有路径都经由它；业务逻辑绝不调用 `os.getcwd()` |
| `filesystem/atomic_writer.py` | `AtomicWriter` —— 先写临时文件再移动，保证配置文件不会写一半 |
| `persistence/profile_codec.py` | `profile.json` 的 v2/v3 JSON 编解码（另有 `v1_profile_codec.py` 与 `v2_to_v3.py` 处理旧版导入） |
| `persistence/profile_repository.py` | Profile 的磁盘 CRUD |
| `persistence/key_repository.py` | 密钥 manifest 管理（`keys/manifest.json` + `.pem` 文件） |
| `persistence/archive_repository.py` | 配置的 ZIP 导入/导出 |
| `persistence/settings_repository.py` | 全局 `settings.json`（`language`、`log_level`）与 `SETTING_DEFS` |
| `fec/` | 空目录——FEC 编码器位于 `avbpowertool/vendor/fec_encoder.py`（numpy + reedsolo，跨平台） |

Persistence 模块被排除在严格 pyright 检查之外（它们在边界处处理无类型的 JSON）。

### presentation/ — CLI 与 TUI

| 模块 | 职责 |
|---|---|
| `actions.py` | `ActionId` StrEnum —— 稳定的机器可读标识符（`image.sign`、`config.import` 等）。CLI 分发、导航和 TUI 绑定都引用这些常量，绝不引用显示字符串 |
| `cli/parser.py` | argparse 设置 + `main()` 入口。无参数 → 启动 TUI；有参数 → CLI 分发 |
| `cli/handlers.py` | `dispatch()` 将解析后的参数映射为用例调用；每个命令一个 `_handle_*`。构建 Request 对象，把结果传给渲染器 |
| `cli/renderer.py` | `render_*` 函数——以文本或 JSON（`--json`）输出 |
| `tui/app.py` | `App` —— curses 主循环。读取 `resources/navigation.json`，渲染当前路由，经 `_()` 翻译标签，分发动作 |
| `tui/router.py` | `Router` —— 加载并校验 `navigation.json`；管理路由、导航项与返回/退出语义 |
| `tui/views/` | 每个屏幕一个模块（`sign_images.py`、`read_image_info.py`、`settings.py` 等）。各自暴露遵循 `docs/zh/FRONTEND_PAGES.md` 约定的 `show(...)` 函数 |
| `tui/widgets.py` | 可复用的 curses 控件（`SelectorWidget`、`message_screen`、输入控件） |
| `audit.py` | 审计日志——会话、导航、选择、确认、动作开始/结束 |
| `i18n.py` | gettext 封装（`_()`、`init_i18n`、`check_l10n`）。详见 `docs/zh/I18N.md` |

## 组合根

`bootstrap.py` 是唯一组装具体实现的地方：

```
bootstrap(root, language)
  1. WorkspacePaths.discover(root)          # 解析目录布局
  2. SettingsRepository.load()              # 读取持久化设置
  3. init_i18n(language)                    # 语言来自参数或设置
  4. setup_logging(...)                     # 带时间戳的会话日志
  -> WorkspacePaths
```

CLI 与 TUI 入口都先调用 `bootstrap()`，再自行构建适配器（`SubprocessAvbTool`、各仓储）和用例。没有全局服务定位器；每个视图/处理器只接收自己需要的依赖。

## 运行时工作区布局

```
<工作区根目录>/
  avbtool.py                  # 内嵌 AOSP 工具（开发仓库根目录也有一份）
  Images/                     # 设备本地的镜像文件（gitignored）
  profiles/<profile>/         # 可跨设备携带的配置（gitignored）
    profile.json
    keys/                     # .pem 文件 + manifest.json
  Logs/                       # 会话日志 + 审计日志（gitignored）
  .avbpowertool-staging/      # 签名期间的临时副本（gitignored）
  settings.json               # 全局设置（gitignored）
```

镜像放在工作区层级（而非 profile 内部），使配置 + 密钥可以跨设备携带，而镜像是设备本地的。`WorkspacePaths.resolve_image_path()` 会拒绝逃逸出 `Images/` 的路径（`workspace.path_escape`）。

## 关键数据流

### 检查镜像

```
CLI/TUI -> InspectImagesUseCase -> AvbToolPort.info_image (子进程)
        -> output_parser.parse_info_image -> ImageInspection -> 渲染器/视图
```

### 签名镜像

```
CLI/TUI -> SignImagesUseCase
        -> SigningPlanBuilder (domain: 依赖图排序步骤、暂存副本)
        -> AvbToolPort (erase/hash/hashtree footer、vbmeta 命令)
        -> ProgressSink 事件 + OperationIssue 列表
        -> SignImagesResult
```

footer 命令会就地修改镜像，因此计划会先在 `.avbpowertool-staging/` 下暂存副本再执行。

### 配置导入/导出

```
ZIP 文件 -> ArchiveRepository -> ProfileCodec (v2/v3) -> ProfileRepository
```

旧版 1.x 归档走 `v1_profile_codec` + `v2_to_v3` 迁移。

## 测试策略

```
tests/
  unit/          # 领域逻辑、编解码、解析器、构建器（无 I/O；必要时用 tmp_path）
  integration/   # 用例 + 假适配器（FakeAvbTool）、TUI 路由、bootstrap i18n
  contract/      # navigation.json schema 校验
  fixtures/      # avbtool 输出样例、profile/manifest 字典
```

- `tests/conftest.py` 提供 `tmp_workspace`、`FakeAvbTool` 和示例 profile/manifest fixture。`FakeAvbTool` 在内存中实现 `AvbToolPort`，用例测试因此从不真正调用子进程。
- 测试绝不读取真实的 `Keys/`、`Images/` 和用户 profile 目录；一律使用 `tmp_path`。
- 契约测试守护 `resources/navigation.json`（所有引用的 action/route 必须存在、起始路由有效），TUI 导航因此不会悄然损坏。

## 横切关注点

- **错误码**：领域异常携带稳定的点分错误码（`config.key_missing`、`image.not_found`、`signing.step_failed` 等）。渲染器和视图可以据此匹配，也会出现在 JSON 输出中。
- **日志**：仅用标准库 `logging`。每个会话在 `Logs/` 打开一个带时间戳的文件；审计事件经 `presentation/audit.py` 写入专用审计 logger。
- **i18n**：只有 presentation 层做翻译；见 `docs/zh/I18N.md`。
- **原子写入**：所有配置/manifest 持久化都经过 `AtomicWriter`（临时文件 + 移动），写入中途崩溃也不会损坏 profile。

## 扩展点

- **新增用例**：`commands.py` 定义类型 → `services/` 实现 → CLI parser/handler/renderer → `ActionId` → 可选的 TUI 视图 + `navigation.json` 条目。详细清单见 `AGENTS.md` 的「Adding a New Use Case」、`docs/zh/FRONTEND_NAVIGATION.md`、`docs/zh/FRONTEND_PAGES.md`。
- **新增 avbtool 操作**：扩展 `domain/command_spec.py` + `domain/command_builder.py`，为 `AvbToolPort` 和 `SubprocessAvbTool` 增加方法，然后在用例中调用。
- **新增存储格式版本**：在 `infrastructure/persistence/` 中新增 codec 和迁移模块（参照 `v1_profile_codec` + `v2_to_v3` 模式）。
