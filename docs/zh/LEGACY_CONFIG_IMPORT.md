# 实现计划：v2 TUI 设置页导入 v1 配置（自动转 v2）+ v2 支持 NONE 签名算法

> 状态：✅ 已实现（见第 10 节实施顺序）  ·  目标版本：schema_version 2  ·  关联参考代码：`references/AVBPowerTool/`

## 1. 目标与已锁定决策

1. **接入位置**：在 v2 TUI **设置页**（`route:settings`）新增独立动作 `action:settings.import_legacy`（快捷键 `I`），用于导入 v1（AVBPowerTool 1.x）导出的配置 zip，**导入时自动转换为 v2 配置**。
2. **NONE 算法**：让 v2 全面支持 `SigningAlgorithm.NONE`（无密钥签名 / 未签名 footer），因为真实 v1 配置里大量分区是 `Algorithm: NONE`（样本 `ZUXOS_411` 15 个分区中 10 个）。
3. 现有 v2 导入链路（`action:config.import` / `ConfigImportUseCase` / `ArchiveRepository`）**保持只认 v2 包不动**，新功能走独立链路。

## 2. 前置改动：v2 支持 NONE 签名算法

vendored `avbtool.py` 已确认：`--algorithm` 默认 `NONE`、`--key` 可选；算法为 `NONE` 时跳过哈希/签名计算（`generate_vbmeta_blob` 中 `if algorithm_name != 'NONE'`）。因此"NONE 签名"= 在 footer / vbmeta 命令中**省略 `--algorithm` 与 `--key`**（hash/hashtree 仍传 `--hash_algorithm`），与 v1 行为一致。

### 2.1 `domain/validation.py`
- `_VALID_SIGNING_ALGORITHMS` 加入 `SigningAlgorithm.NONE`（NONE 对 hash/hashtree/vbmeta 均为合法）。
- `validate_partition`：仅当 `algorithm != NONE` 时才要求 `key_id` 非空（当前无条件报 `config.key_missing`）；NONE 分区允许 `key_id == ""`。
- `config.vbmeta_no_contents` 规则不变（NONE 的 vbmeta 仍须有 included/chain 内容）。

### 2.2 `domain/signing_plan.py`（关键执行路径）
- `_build_non_vbmeta_step`：`algorithm == NONE` 时不调用 `_resolve_key_path`（`key_path = None`），否则照旧。
- `_build_hash_command` / `_build_hashtree_command`：`key_path: Path | None = None`；`--algorithm`/`--key` 仅在非 NONE 且 `key_path` 存在时追加；`--hash_algorithm` 始终追加（NONE 分区也必须显式传 `sha256`，避免 avbtool 的 sha1 回退警告）。
- `_build_vbmeta_step`：同样——NONE 时 `key_path = None`、省略 `--algorithm`/`--key`；其余（`--rollback_index`、flags、included、chain、props）不变。
- **顺带修复 chain 公钥路径解析**（现有 v2 小缺口）：`_build_vbmeta_step` 对每个 `chain_partitions` 条目，若第三个字段（公钥文件）非绝对路径，则相对 `self._key_dir` 解析后重新拼装 `"name:loc:resolved_keyfile"`。这样 v1 转来的 `"boot:3:testkey_rsa4096_pub.bin"` 能被正确解析。

### 2.3 `application/ports.py` + `infrastructure/avbtool/runner.py`
- `add_hash_footer` / `add_hashtree_footer` / `make_vbmeta_image` 的 `key_path: Path` 改为 `key_path: Path | None = None`。
- runner 中三个方法：`key_path is not None` 时才追加 `--algorithm <alg> --key <path>`；NONE 时两者都省略（与 v1 完全一致）。

### 2.4 `infrastructure/avbtool/command_builder.py`
- `build_hash_footer_command` / `build_hashtree_footer_command` / `build_vbmeta_command`：同样把 `key_path` 置为可选，NONE 时省略 `--algorithm`/`--key`（该模块被单元测试使用，保持一致性）。

### 2.5 `tests/conftest.py` `FakeAvbTool`
- 三个方法签名同步为 `key_path: Path | None = None`（仅记录调用，无需改逻辑）。

### 2.6 验证
- `uv run pytest tests/unit/test_validation.py tests/unit/test_signing_plan.py tests/unit/test_runner.py tests/unit/test_command_builder.py tests/integration/test_sign_images.py -q`

## 3. 新增：v1 → v2 转换 codec

### 新文件 `avbpowertool/infrastructure/persistence/v1_profile_codec.py`
（与 `profile_codec.py` 同层；纯函数优先，I/O 集中在解包函数）

```python
V1_ARCHIVE_FLAG = "this_is_a_config_file_of_avbpowertool"
V1_BATCH_FLAG = "BATCH_CONFIG_AVBPOWERTOOL"
V1_RENAME_FLAG = "RENAME_REQUIRED"

def detect_v1_archive(archive_path: Path) -> str:
    """返回 "single" | "batch" | "none"（按 zip 内标志文件判定）。"""

def extract_v1_archive(archive_path: Path, staging_dir: Path) -> Path:
    """校验路径安全（复用 _validate_archive_path 思路）后解包，返回含 Configs/、Keys/ 的目录。
    拒绝路径穿越；批量包由上层拦截。"""

def decode_v1_image_info(raw: dict[str, Any], config_id: str) -> tuple[AvbProfile, list[OperationIssue]]:
    """把 v1 imageInfo.json 字典纯转换为 v2 AvbProfile（含告警 issues）。"""

def build_key_manifest(keys_dir: Path, key_cache: Path | None) -> tuple[dict[str, dict[str, str]], list[OperationIssue]]:
    """扫描 *.pem → manifest；读 keyCache.cache 填 public_key_sha1；复制 _pub.bin 为 public_key。"""
```

### 3.1 v1 → v2 字段映射表

| v1（imageInfo.json 条目） | v2 `PartitionConfig` | 说明 |
|---|---|---|
| 条目键 / `Partition Name` | partitions 键 + `partition_name` | 优先 `Partition Name` |
| `Image File` | `image` | |
| 文件名含 `vbmeta` 或含 `Chain` 键 → VBMETA；否则 `Descriptor Type` | `descriptor` | v1 vbmeta 条目无 `Descriptor Type`，启发式判定 |
| `Algorithm` | `algorithm` | `NONE` → `SigningAlgorithm.NONE`（v2 现已支持） |
| `Public key file`（去 `.pem`） | `key_id` | `NOT_FOUND`/缺失 → 告警 `import.legacy.key_not_found` |
| `Rollback Index`（字符串） | `rollback_index: int` | |
| `Salt` | `salt` | |
| `Flags`（字符串） | `flags: int` | |
| `Props`（dict） | `props: tuple[tuple[str,str], ...]` | |
| `Hash Algorithm` | `hash_algorithm` | 缺省 `sha256` |
| `Data Block Size` / `Hash Block Size`（去 `" bytes"`） | `data_block_size` / `hash_block_size` | 缺省 4096 |
| vbmeta：`Hash` + `Hashtree` 拼接 | `included_partitions` | |
| vbmeta：`Chain[i]` + `Chain partition key[i]` | `chain_partitions` → `f"{name}:{loc}:{pubbin}"` | 把 v1 残缺三元组补全为 v2 三元组；长度不匹配 → 告警 `import.legacy.partial_chain` |
| `Root Digest`、`Version of dm-verity`、`Image size` | （无对应字段，丢弃） | 仅信息性；`Image size` 见第 9 节限制 |

### 3.2 密钥与 manifest
- 复制 v1 `Keys/` 下所有 `*.pem` 到 `profiles/<id>/keys/`；`_pub.bin` 一并复制。
- `manifest`：`key_id = pem 名去 .pem` → `{"private_key": "...", "public_key": "..._pub.bin", "public_key_sha1": "..."}`（sha1 来自 `keyCache.cache`，缺失留空）。
- 与 v2 `KeyDiscoveryUseCase` 输出形态一致，导入后可用"管理密钥"页复查。

### 3.3 配置名/ID 推导
用户输入 `new_profile_id` → v1 `config_info.cfg` 的 `name` → zip 文件名去 `.zip`；做安全化（去非法字符、防覆盖已有 profile）。`config.cfg`/`config_info.cfg` **不作为必需文件**（真实样本里不存在）。

## 4. 新增：`LegacyConfigImportUseCase`（application 层）

### `application/commands.py`
```python
@dataclass(frozen=True)
class LegacyImportRequest:
    archive_path: str
    new_profile_id: str | None = None
    activate: bool = True

@dataclass(frozen=True)
class LegacyImportResult:
    profile_id: str
    partition_count: int
    key_count: int
    issues: tuple[OperationIssue, ...] = ()
```

### `application/services/manage_configs.py`
新增 `LegacyConfigImportUseCase.execute()`：
1. `detect_v1_archive` → 非 `single` 返回 `config.invalid_archive`（批量包给出明确提示）。
2. `extract_v1_archive` 解包到 `ws.staging`（沿用路径穿越校验）。
3. 读 `Configs/imageInfo.json` + `Keys/`；`decode_v1_image_info` + `build_key_manifest` 得 `AvbProfile` + manifest（收集转换告警）。
4. 目标 id 冲突 → `config.profile_exists`（或自动加后缀，见 UI 决策）。
5. `ProfileRepository.save(profile)`；复制 pem/pub.bin；`KeyRepository.save_manifest`；按 `activate` 调 `ProfileRepository.activate`。
6. 返回 `LegacyImportResult`（含 partition/key 计数与 issues）。失败时清理 staging。

## 5. TUI 设置页集成

### 5.1 `resources/navigation.json`
- `route:settings.items` 追加 `{"action": "action:settings.import_legacy", "shortcut": "I"}`（E/V/C/I 在 settings 路由内唯一）。
- `actions` 追加：
```json
"action:settings.import_legacy": {
  "label_key": "settings.action.import_legacy",
  "description_key": "settings.action.import_legacy_description"
}
```

### 5.2 `presentation/tui/views/settings.py`
新增 `show_import_legacy(stdscr, ws, avb)`，交互流（复用现有 widget，参考 `import_config.show`）：
1. 扫根目录 `*.zip`；无 → `message_screen` 提示返回。
2. `SelectorWidget` 选归档。
3. `input_prompt` 新 profile id（回车=按归档名）；再 `input_prompt` 显示名（回车=用 id）。
4. `confirm_dialog` 确认转换导入（可选：追加"是否激活"确认）。
5. 调 `LegacyConfigImportUseCase` → `message_screen` 展示导入 id、分区/密钥数、全部 issues。

### 5.3 `presentation/tui/app.py`
`view_map` 注册 `"action:settings.import_legacy": settings.show_import_legacy`。

### 5.4 i18n（`locale/en` 与 `locale/zh` 的 `avbpowertool.po`）
`settings.action.import_legacy`、`settings.action.import_legacy_description`、`settings.import_legacy.title`、`settings.import_legacy.select_archive`、`settings.import_legacy.enter_profile_id`、`settings.import_legacy.enter_profile_name`、`settings.import_legacy.confirm`、`settings.import_legacy.activate`、`settings.import_legacy.success`、`settings.import_legacy.failed`、`settings.import_legacy.not_legacy`、`settings.import_legacy.batch_not_supported`、`settings.import_legacy.no_zip_found`、`settings.import_legacy.key_not_found`、`settings.import_legacy.partial_chain`、`settings.import_legacy.profile_exists` 等。

## 6. CLI（可选，推荐）

- `ActionId.CONFIG_IMPORT_LEGACY = "config.import_legacy"`（`presentation/actions.py`）。
- `parser.py`：`config import-legacy <archive> [--profile ID] [--name NAME] [--no-activate] [--json]`。
- `handlers.py` + `renderer.py` 复用同一 use case。实现三态（TUI/CLI/API）统一能力。

## 7. 测试计划

- **unit `tests/unit/test_v1_profile_codec.py`**：用 `tests/fixtures/legacy/`（从 `references/AVBPowerTool/Configs/ZUXOS_411/` 复制静态样本，测试**不**直接读 references）断言：各分区字段映射、vbmeta `included_partitions`/`chain_partitions` 补全、NONE 转换、`NOT_FOUND` 密钥告警、`Data/Hash Block Size` 去后缀、`Chain` 长度不匹配告警。
- **unit `tests/unit/test_legacy_archive.py`**：标志文件判定（single/batch/none）、路径穿越拒绝。
- **unit 扩展**：`test_validation.py`（NONE 合法、NONE 不强制 key_id）、`test_signing_plan.py`（NONE 命令无 `--algorithm/--key`、chain 公钥相对 key_dir 解析）、`test_runner.py` / `test_command_builder.py`（NONE 命令形态）。
- **integration `tests/integration/test_legacy_import.py`**：构造 v1 zip（`Configs/`+`Keys/`+标志文件）→ 调 use case → 断言 `profiles/<id>/profile.json` 可被 `decode_profile` 反解、pem/pub.bin 已复制、manifest 正确、可激活；并断言同一 v1 zip 经现有 `ConfigImportUseCase` 会被拒绝（两套导入互不干扰）。
- **contract**：现有 `tests/contract/test_navigation_schema.py` 覆盖新导航项。
- **手工**：`uv run avbpowertool` → Settings → 导入 v1 zip → 查看结果与 issues；`uv run avbpowertool config import-legacy ...`（若实现 CLI）。

## 8. 验收流程（AGENTS.md 管道）

```
1. 改代码
2. uv run pytest tests/
3. uv run ruff check avbpowertool
4. uv run ruff format avbpowertool
5. uv run pyright avbpowertool
6. git add + git commit
```

## 9. 已知限制（记录在案，非本期范围）

- **`--partition_size`（v1 `Image size`）**：v2 `PartitionConfig` 无此字段，转换后不保留；v2 签名也不传 `--partition_size`。若需要可作为后续增强。
- **v1 BATCH 归档**：本期设置页导入只支持单配置包，批量包明确拒绝并提示。
- **`config.cfg` / `config_info.cfg` / `imageList.txt`**：非必需；名称回退链见 3.3；`imageList.txt` 不迁移（v2 以 partitions 字典为准）。
- **vbmeta 判定**：按"文件名含 `vbmeta` 或条目含 `Chain` 键"启发式。
- **v1 根目录 zip 选取**：沿用现有导入视图只扫项目根目录 `*.zip` 的模式。
- **转换幂等性**：转换只读 v1 包、只写新 profile 目录，不修改 v1 源文件。

## 10. 实施顺序（Definition of Done）

1. NONE 支持（2.1–2.5）→ 相关测试绿。
2. v1 codec（第 3 节）→ unit 测试绿。
3. `LegacyConfigImportUseCase` + commands（第 4 节）→ integration 测试绿。
4. TUI 设置页集成（第 5 节：nav / view / app / i18n）。
5. CLI（第 6 节，可选）。
6. 文档更新（README、`docs/en|zh/CONFIG_CREATION.md` 注明 NONE 支持与旧配置导入）。
7. 全量管道（第 8 节）通过后提交。
