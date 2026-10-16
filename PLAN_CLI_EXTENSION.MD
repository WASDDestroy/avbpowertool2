# CLI 扩展改动清单（PLAN_CLI_EXTENSION.MD）

> 目标：把"生成 testkey 测试签名配置 → 读镜像 AVB 元数据 → 改链式/密钥/算法 → 改名 → 导出 zip"
> 这条 OEM 打包流程从"只能靠 TUI + 手改 JSON"提升为**可被 shell / BAT / Python 脚本完整驱动**的 CLI。
>
> 本文只描述改动面与实施顺序，不含实现代码。所有结论均已在本仓库当前 HEAD 上实测或读码确认。

---

## 1. 现状核查（问题清单与证据）

### 1.1 CLI 命令面现状

`avbpowertool/presentation/cli/parser.py:18-155` 现有命令：

```
image   inspect | sign
config  show | validate | list | activate | import | import-legacy | export | migrate | edit
about
read | sign | get_all_config | check_l10n        (deprecated 别名)
```

缺失：`config create`、`config rename`、`config check-*`、任何 `keys` 命令、任何 `profile` 顶层命令。

### 1.2 阻断项（P0：不修就无法用脚本完成目标流程）

| # | 问题 | 证据 | 实测 |
|---|---|---|---|
| B1 | `"current"` 从不解析为活动配置；`image sign` / `config show` / `config validate` 连 `--profile` 参数都没有 | `profile_repository.py:88-96`（只有 `get_active_profile_id()`，无解析入口）；`commands.py:28,49,83,109` 默认 `"current"`；`parser.py:30-70` 无 `--profile`；`handlers.py:142-184` 未传 `profile_id` | `avbpowertool config show --json` → `config.not_found: Profile not found: current`（exit 1）；`avbpowertool image sign boot --dry-run` → 同样失败 |
| B2 | `config edit` 不能改 `key_id` / `algorithm` | `manage_configs.py:494-541` 的 `_INT/_BOOL/_STR/_TUPLE_FIELDS` 均不含这两个字段 | `config edit boot --set key_id=...` → `config.invalid_field`；`--set algorithm=SHA256_RSA2048` → 同 |
| B3 | 无 `config create`；`ConfigCreateUseCase` 拒绝空分区（连目录都不建） | `manage_configs.py:369-382`；`validation.py:57-59`（`config.no_partitions`） | 无法"先建空配置、后灌分区" |
| B4 | 无 `keys` 命令；`chain_partitions` 第三段必须是 `extract_public_key` 产物（`*.pem.bin`），而 `for_agents/` 只有 `.pem` | `avbtool.py:3216-3217`（第三段按原始字节读入 `desc.public_key`）；`manage_keys.py:59-107`；`renderer.py:397-417` 已有 `render_key_discovery` 但无人调用 | `uv run python avbtool.py extract_public_key --key for_agents\testkey_rsa4096.pem --output <out>` 可用（1032 字节，与 `profiles/tb710fu-470-no-ubl/keys/*.pem.bin` 一致） |
| B5 | 无 rename 能力 | `manage_profiles.py` 只有 List/Activate/Delete | — |

### 1.3 能力缺口（P1/P2：决定脚本能有多"薄"）

| # | 缺口 | 证据 |
|---|---|---|
| G1 | 从镜像自动生成配置的逻辑只存在于 TUI view 的私有函数里 | `presentation/tui/views/create_config.py:210-471`（`_build_auto_partition` / `_finalize_vbmeta_includes` / `_apply_chain_resolutions` / `_key_for_algorithm`），application 层无对应用例 |
| G2 | `_finalize_vbmeta_includes` 的兜底会"把其它所有非 vbmeta 已扫描分区塞进该 vbmeta" | `create_config.py:442-447`；单测 `tests/unit/test_create_config_wizard.py:184-206` 正是在固化这个行为 |
| G3 | `KeyDiscoveryUseCase` 整体重写 manifest，丢掉已有 `public_key` | `manage_keys.py:90-101`（`manifest = {}` 后重建） |
| G4 | 无链式一致性校验：chain 条目公钥与被链分区实际签名密钥可以不一致而无人报错 | 现有 `profiles/tb710fu-470-no-ubl/profile.json:171-175` 链为 `vbmeta_system:2:testkey_rsa2048.pem.bin`，但 `vbmeta_system` 的 `key_id` 是 `testkey_rsa4096`（`:177-183`）→ 按此签名必然校验失败 |
| G5 | `exit_code_from_issues` 对未知错误码前缀返回 0 | `renderer.py:430-441`（只识别 `tool/signing/config/keys/image`） |
| G6 | `config show --json` 输出字段过少（无 `flags`/`chain_partitions`/`included_partitions`/`salt`），脚本难以复核步骤 4 结果 | `renderer.py:176-207` |

### 1.4 明确不做（留在包装脚本层）

- `--core / --mi / --oplus / --8e / --no_hashtree_*` 旗标表、`odm_dlkm`/`my_preload`/`my_company` 条件追加：属 OEM 打包策略，不入库（保持 domain 无 I/O、无厂商知识）。
- `--no_prompt` / `--no_export`：包装层开关。
- `config edit --set descriptor=...`：descriptor 与 image/字段组合强耦合，改动语义风险高，显式不支持。

---

## 2. 设计原则（必须遵守）

1. 依赖方向 `presentation → application → domain`；新逻辑一律落在 application/domain，CLI 只做参数解析与渲染。
2. 每个 action 用 `ActionId` 常量派发，禁止用字符串/参数名派发（`presentation/actions.py`）。
3. 错误码稳定、点分前缀：`config.*` / `keys.*` / `image.*` / `chain.*` / `signing.*` / `tool.*`；用例返回 `OperationIssue` 元组，不抛异常。
4. 所有新命令支持 `--json`；`--json` 与文本输出走同一个 result 对象。
5. CLI 输出沿用现状（英文硬编码），不引入 gettext；i18n 仅用于 TUI。
6. 只读命令（show/validate/check-chains）绝不写盘；写盘走 `ProfileRepository.save`（原子写）。
7. 任何 `save` 都会用 `encode_profile` **重排/省略默认值**地重写整个 `profile.json`——文档与测试需知悉这一点。

---

## 3. 改动清单

### P0-1 · profile 解析与 `--profile` 补全

**目标**：`current` 能解析为 `.active-profile` 指向的配置；`image sign` / `config show` / `config validate` 可指定配置。

**解析规则（关键：字面优先，保证向后兼容）**

```
resolve_profile_id(ws, requested):
    1) requested 非空且 profiles/<requested>/profile.json 存在  -> requested        # 兼容名为 "current" 的真实配置
    2) requested in {"", "current"} 且 .active-profile 指向存在的配置 -> 活动 id
    3) 否则 -> ConfigError("config.not_found")；有 current 语义但无活动配置 -> ConfigError("config.no_active_profile")
```

**API**

- `infrastructure/persistence/profile_repository.py`：新增 `resolve_profile_id(self, requested: str) -> str`（+10 行）。
- `application/services/`：调用点统一改用 `repo.resolve_profile_id(request.profile_id)`：
  `ConfigShowUseCase`、`ConfigValidateUseCase`、`ConfigEditUseCase`、`ConfigMigrateUseCase`（`manage_configs.py`）、
  `SignImagesUseCase`（`sign_images.py:57-59`）、`ResolveChainKeysUseCase`（`resolve_chains.py:40`）、
  `KeyDiscoveryUseCase`/`KeyListUseCase`/`KeyAddUseCase`/`KeyRemoveUseCase`（`manage_keys.py`）。
- 新错误码：`config.no_active_profile`。

**CLI**

```
image sign        <images...> [--profile ID] ...
config show                   [--profile ID] [--json]
config validate               [--profile ID] [--json]
```

- `parser.py`：给上述三个子命令加 `--profile`（默认 `"current"`）。
- `handlers.py`：把 `profile_id` 传入 request（`SignImagesRequest` / `ConfigShowRequest` / `ConfigValidateRequest` 已有该字段，只需接线）。
- `config export` 保持位置参数 `<profile>` 必填（脚本始终知道 id），不改为默认活动配置。

**测试**：`tests/integration/test_cli_contract.py` 新增"无活动配置 → `config.no_active_profile`（exit 1）"、"有活动配置 → `config show --json` 成功"、"存在字面名为 `current` 的配置时优先用字面 id"（守住 `conftest.tmp_workspace` 的既有布局）。

**风险**：中低。唯一行为变更是原本报错的调用现在可能成功；需回归 `tests/` 全量。

---

### P0-2 · `config edit` 扩字段 + `--unset` / `--append` / `--remove`

**目标**：步骤 4 全部可走 CLI，不再手改 JSON；并提供"按分区名替换链式条目"的合并语义。

**CLI**

```
avbpowertool config edit <PARTITION> [--profile ID]
    --set    FIELD=VALUE        # 已有；标量字段
    --unset  FIELD              # 新增：str->""，int->0，bool->False，tuple->()
    --append FIELD=ITEM         # 新增：仅元组字段；可重复
    --remove FIELD=ITEM         # 新增：仅元组字段；可重复
    [--json]
```

**字段扩展**（`manage_configs.py`）

| 字段 | 类型 | 处理 |
|---|---|---|
| `key_id` | str | 直接赋值；允许空串（NONE 分区） |
| `algorithm` | enum | `SigningAlgorithm.from_str()`；非法 → `config.invalid_algorithm` |
| `image` | str | 直接赋值；建议校验 `.img` 结尾，否则 `config.invalid_field` |
| `props` | tuple[tuple] | `KEY:VALUE` 逗号分隔（与 `kernel_cmdlines` 同风格，但值为二元组） |

**`--append` / `--remove` 语义**

- 普通元组字段：追加 / 删除完全匹配项。
- `chain_partitions` / `chain_partitions_do_not_use_ab`：`ITEM` 可以是完整三元组，也可以只是分区名；
  - `--append chain_partitions=boot:3:testkey_rsa4096.pem.bin`：若已存在同名分区条目 → **替换该条**（即"重名替换"），否则追加；
  - `--remove chain_partitions=vbmeta_vendor`：按分区名删除。
- 这一步直接满足"硬编码链式数据、重名替换"的需求，且不会像 `--set` 那样清掉镜像里读回的其它链。

**校验**：改动后可选跑 `validate_partition`（`domain/validation.py:67`），把问题作为 issue 返回但**不阻断**写入（与现状 `ConfigEditUseCase` 一致）；非法值仍阻断。

**测试**：扩展 `tests/integration/test_config_migrate_edit.py::TestConfigEditUseCase`：
`key_id`/`algorithm` 可改、非法算法被拒、`--unset` 清空、`--append` 同名替换、`--remove` 按分区名删除。

**风险**：低。字段白名单是唯一入口，回归面小。

---

### P0-3 · `keys` 子命令

**CLI**

```
avbpowertool keys list          [--profile ID] [--json]
avbpowertool keys discover      [--profile ID] [--merge|--replace] [--json]
avbpowertool keys ensure-public [--profile ID] [--json]      # extract_public_key -> <name>.pem.bin，并回写 manifest
avbpowertool keys add    <KEY_ID> --file <NAME.pem> [--profile ID] [--json]
avbpowertool keys remove <KEY_ID> [--profile ID] [--json]
```

**行为**

- `discover` 默认改为**合并**（保留已有 `public_key` / `public_key_sha1` 字段），`--replace` 恢复旧的覆盖语义（G3）。
- `ensure-public`：包装 `application/services/manage_keys.py:25-56` 的 `ensure_public_keys()`，需要 `AvbToolPort`（`handlers.py:61-62` 已有工厂）。
- 新增 result：`KeyEnsurePublicResult(extracted: tuple[tuple[str, str], ...], issues)`（`commands.py`），
  其余复用 `KeyDiscoveryRequest/Result`、`KeyListRequest/Result`、`KeyAddRequest/Result`、`KeyRemoveRequest/Result`。
- renderer：复用 `render_key_discovery`，新增 `render_key_list` / `render_key_ensure_public`。

**ActionId**：`KEY_LIST` / `KEY_DISCOVER` / `KEY_ENSURE_PUBLIC` / `KEY_ADD` / `KEY_REMOVE`。

**测试**：`tests/integration/test_manage_keys.py` 或新增 `tests/integration/test_cli_keys.py`：
manifest 合并语义、`ensure-public` 调用 `extract_public_key`（用 `FakeAvbTool` 断言 `calls`）、`--json` 契约。

**风险**：低。

---

### P1-1 · `config create`（可建空配置）

**CLI**

```
avbpowertool config create --id <ID> [--name <NAME>]
                           [--activate|--no-activate] [--allow-empty] [--json]
```

- `--allow-empty`：允许零分区创建（步骤 1 的"先建配置、再放密钥、再灌分区"）。
- 实现：`ConfigCreateRequest.allow_empty: bool = False`（`commands.py:144-159`）；
  `ConfigCreateUseCase.execute` 在 `allow_empty` 时跳过 `config.no_partitions` 早退（`manage_configs.py:369-382`），其余校验照旧；`domain/validation.py` 保持严格（domain 不因 CLI 便利性放宽）。
- 落盘内容：`profiles/<ID>/profile.json`（空 partitions）、`profiles/<ID>/keys/`、`keys/manifest.json`（`{}`）。
- profile id 校验：复用 `_sanitize_profile_id`（`manage_configs.py:299-302`），非法 → `config.invalid_profile_id`（新码）；重名 → `config.profile_exists`（已有）。

**测试**：`tests/integration/test_manage_configs.py` 新增 `allow_empty` 用例；CLI 契约测试新增 `--help` + 空配置创建 + `--json`。

**风险**：低。

---

### P1-2 · 抽出自动生成用例 + `config create --from-images`

**重构（无行为变更）**

- 新模块 `application/services/config_auto_create.py`，迁入并公开：
  `build_auto_partition()`、`finalize_vbmeta_includes()`、`apply_chain_resolutions()`、`select_key_for_algorithm()`、`VALID_HASH_ALGORITHMS`（源：`presentation/tui/views/create_config.py:341-471`）。
- `create_config.py` 改为从新模块导入并调用（TUI 交互逻辑保留在 view）。
- 单测 `tests/unit/test_create_config_wizard.py` 的 import 改到新模块；`_auto_dir_default` 与 `_collect_partitions_auto` 的交互测试保留在 view 层。

**新用例**

```python
@dataclass(frozen=True)
class ConfigAutoCreateRequest:
    profile_id: str
    profile_name: str
    image_dir: Path | None = None        # 默认 ws.images
    image_names: tuple[str, ...] = ()    # 空 = 目录内全部 .img（按名排序）
    key_id: str | None = None            # 覆盖自动 key 选择
    resolve_chains: bool = True
    include_fallback: bool = False       # 见 G2
    skip_non_avb: bool = False           # 无 AVB 结构镜像是否跳过
    overwrite: bool = False
    activate: bool = True

@dataclass(frozen=True)
class ConfigAutoCreateResult:
    profile_id: str
    partition_count: int
    chain_count: int
    skipped_images: tuple[str, ...] = ()
    issues: tuple[OperationIssue, ...] = ()
```

**行为要点**

1. 只扫描 `image_names`（为空则扫描 `image_dir/*.img`），逐张 `InspectImagesUseCase`。
2. `descriptor is None`（无 AVB 结构）：默认产生 `image.no_vbmeta_structure` 并**失败退出**；`skip_non_avb=True` 时才跳过并记入 `skipped_images`（G1 的静默丢分区风险必须显式化）。
3. `include_fallback=False`（CLI 默认）：vbmeta 的内嵌描述符被剪空且无链时，不再"塞入全部"，改为报 `config.vbmeta_no_contents`（已有码）；TUI 传 `True` 保持旧行为（`tests/unit/test_create_config_wizard.py:184-206` 继续通过）。
4. `resolve_chains=True`：走 `ResolveChainKeysUseCase`（公钥 sha1 → key store 文件）；解析不到只记 issue，不阻断（步骤 4 会硬编码链）。
5. `overwrite=True`：同 id 已存在时以新分区集合覆盖（保留 `keys/` 内容）；否则 `config.profile_exists`。
6. 生成后可选跑一次 `ConfigValidateUseCase`，把 `missing_images` / `missing_keys` 并入 result（便于脚本一次拿到全部问题）。

**CLI**

```
avbpowertool config create --id <ID> [--name <NAME>]
                           [--from-images [DIR]] [--images a,b,c]
                           [--key KEY_ID] [--no-chain-resolve]
                           [--include-fallback] [--skip-non-avb]
                           [--overwrite] [--activate|--no-activate] [--json]
```

- `--from-images` 不带值时用 `<root>/Images`；带 `--images` 时只处理列出的名字（**镜像集合由包装脚本按旗标表算好再传入**）。
- `--from-images` 与 `--allow-empty` 互斥（argparse 层校验 → `config.invalid_option_combination`，已有码）。

**ActionId**：`CONFIG_CREATE`（空配置）/ `CONFIG_AUTO_CREATE`（从镜像）——或合并为同一 action 由请求字段区分；**建议合并为 `CONFIG_CREATE`**，减少 i18n/文档重复。

**测试**：新 `tests/integration/test_config_create_cli.py`：
`--from-images` 生成分区集合、`--images` 子集过滤、vbmeta includes 剪枝（含空 includes 报错路径）、`--skip-non-avb` 行为、`--overwrite`、`--json` 契约。

**风险**：中。动了 TUI 现有路径，必须保证"抽取后 TUI 行为等价"（现有 wizard 单测即回归网）。

---

### P1-3 · `config rename`

**CLI**

```
avbpowertool config rename <OLD> <NEW> [--name <DISPLAY_NAME>] [--json]
```

**用例** `ProfileRenameUseCase`（`application/services/manage_profiles.py`）

1. `NEW` 通过 `_sanitize_profile_id` 校验 → 否则 `config.invalid_profile_id`；
2. `profiles/<NEW>` 已存在 → `config.profile_exists`；
3. `profiles/<OLD>` 不存在 → `config.not_found`；
4. 目录改名（`Path.rename`，失败 → `config.rename_failed`）；
5. 重写 `profile.json` 的 `profile.id = NEW`（`--name` 给定则同时改 `profile.name`），走 `ProfileRepository.save`（保证"目录名 == profile.id"不变式）；
6. 若 `.active-profile == OLD` → 写为 `NEW`。

**测试**：`tests/integration/test_manage_profiles.py`：成功改名、重名拒绝、活动配置改名后 `.active-profile` 同步、`--name` 只改显示名。

**风险**：低中（Windows 目录占用 → 需覆盖 `OSError` 分支）。

---

### P2-1 · `config check-chains`（链式一致性校验，只读）

**CLI**

```
avbpowertool config check-chains [--profile ID] [--json]
```

**校验项**（对每个 vbmeta 分区的每条 `chain_partitions` 条目 `PART:SLOT:KEYFILE`）

1. `PART` 是否在 profile 中 → 否则 `config.missing_included_partition`；
2. `KEYFILE` 是否存在于 key store（相对 key 目录解析，规则同 `signing_plan.py:266-303`）→ 否则 `chain.key_file_missing`；
3. `KEYFILE` 的 sha1 是否等于 `PART` 分区所用 `key_id` 对应公钥的 sha1 → 否则 `chain.key_mismatch`（**直接命中 G4**）；
4. `SLOT` 唯一且 ≥1（`domain/validation.py:208-247` 已有，复用）。

**ActionId**：`CONFIG_CHECK_CHAINS`。新增错误码：`chain.key_mismatch`、`chain.key_file_missing`。

**测试**：构造"链公钥 = 2048 / 被链分区用 4096 签名"的 profile（即当前 `tb710fu-470-no-ubl` 的真实状态）断言报 `chain.key_mismatch`。

**风险**：低（纯读）。

---

### P2-2 · 输出契约与退出码统一

- `renderer.exit_code_from_issues`：把 `chain` 前缀映射为 1（否则新命令出错也返回 0，见 G5）；`keys` 已覆盖。
- `render_config_show` 的 JSON 补全字段：`flags` / `included_partitions` / `include_descriptors_from_image` / `chain_partitions` / `salt` / `partition_size` / `descriptor` / `props`（G6，便于脚本复核步骤 4）。
- 新增 renderer：`render_config_create`、`render_config_rename`、`render_config_check_chains`、`render_key_list`、`render_key_ensure_public`。
- `ActionId` 新增汇总：`CONFIG_CREATE`、`CONFIG_RENAME`、`CONFIG_CHECK_CHAINS`、`KEY_LIST`、`KEY_DISCOVER`、`KEY_ENSURE_PUBLIC`、`KEY_ADD`、`KEY_REMOVE`。

---

## 4. 改动影响矩阵

| 层 | 文件 | 改动性质 | 规模估计 |
|---|---|---|---|
| domain | `domain/validation.py` | 不改（保持严格） | 0 |
| application | `application/commands.py` | 新增 5 个 request/result；`ConfigCreateRequest` 加 `allow_empty` | +80 |
| application | `application/services/manage_configs.py` | 字段白名单扩展、`--unset/--append/--remove` 解析、`allow_empty`、profile 解析接线 | +120 |
| application | `application/services/config_auto_create.py` | **新文件**（自 TUI 迁入 + 用例） | +260 |
| application | `application/services/manage_profiles.py` | `ProfileRenameUseCase` | +90 |
| application | `application/services/manage_keys.py` | `discover` 合并语义、`ensure_public_keys` 结果包装 | +40 |
| application | `application/services/{sign_images,resolve_chains,inspect_images}.py` | profile 解析接线 | +10 |
| infrastructure | `infrastructure/persistence/profile_repository.py` | `resolve_profile_id` | +12 |
| presentation | `presentation/cli/parser.py` | 新增 `keys` 组、`config create/rename/check-chains`、`--profile` 补全、`--unset/--append/--remove` | +110 |
| presentation | `presentation/cli/handlers.py` | 新增 8 个 handler + 接线 | +140 |
| presentation | `presentation/cli/renderer.py` | 5 个新 renderer + `config show` JSON 补全 + 退出码映射 | +120 |
| presentation | `presentation/actions.py` | 8 个 ActionId | +8 |
| presentation | `presentation/tui/views/create_config.py` | 改为调用新用例（净减） | −150 |
| tests | `tests/unit/test_create_config_wizard.py` | import 迁移 + 新模块单测 | ±60 |
| tests | `tests/integration/test_cli_contract.py` 等 | 新增用例 | +250 |
| docs | `docs/zh|en/CONFIG_CREATION.md`、`KEY_MANAGEMENT.md`、`BACKEND_API.md`、`README.md` | 新命令与新用例 | +150 |

不改动：`avbtool.py`（vendor）、`domain/models.py`（无需新字段）、`domain/signing_plan.py`、`domain/command_builder.py`。

---

## 5. 实施顺序（每步一个 commit，各自过完整流水线）

> 每步提交前必须：`uv run pytest tests/` → `uv run ruff check avbpowertool` → `uv run ruff format avbpowertool` → `uv run pyright avbpowertool`。

| # | commit 建议 | 内容 | 依赖 |
|---|---|---|---|
| 1 | `fix(cli): resolve the active profile for current and add --profile` | P0-1 | — |
| 2 | `feat(cli): extend config edit with key_id/algorithm/image/props and append/remove` | P0-2 | — |
| 3 | `feat(cli): add keys list/discover/ensure-public/add/remove commands` | P0-3 | 1 |
| 4 | `feat(cli): add config create with allow-empty` | P1-1 | 1 |
| 5 | `refactor(app): move auto partition generation out of the TUI wizard` | P1-2 重构部分（无 CLI） | — |
| 6 | `feat(cli): add config create --from-images` | P1-2 CLI | 4,5 |
| 7 | `feat(cli): add config rename` | P1-3 | 1 |
| 8 | `feat(cli): add config check-chains and fix chain exit codes` | P2-1, P2-2 | 2,3 |
| 9 | `docs: document the extended CLI surface` | docs | 全部 |

步骤 1、2、5 相互独立，可并行开工；6 必须等 4 与 5。

---

## 6. 测试计划

**单元**

- `tests/unit/test_profile_repository.py`：`resolve_profile_id` 三条规则（字面优先 / current→active / 无活动配置报错）。
- `tests/unit/test_config_auto_create.py`（新）：`build_auto_partition` 全字段读回、`finalize_vbmeta_includes` 剪枝 + 空 includes 报错、`apply_chain_resolutions` 未解析跳过、`skip_non_avb` 行为。
- `tests/unit/test_create_config_wizard.py`：import 迁移后保持全绿（TUI 行为等价）。

**集成**

- `tests/integration/test_cli_contract.py`：新命令 `--help`、`--json` 合法性、退出码（含 `chain.*` → 1）。
- `tests/integration/test_config_migrate_edit.py`：`key_id`/`algorithm`/`--unset`/`--append` 同名替换/`--remove`。
- `tests/integration/test_config_create_cli.py`（新）：空配置、`--from-images` + `--images` 子集、`--overwrite`、`--allow-empty` 与 `--from-images` 互斥。
- `tests/integration/test_manage_profiles.py`：rename 成功/重名/活动配置同步。
- `tests/integration/test_manage_keys.py`：discover 合并语义、`ensure-public` 触发 `extract_public_key`。
- `tests/integration/test_config_check_chains.py`（新）：`chain.key_mismatch`（用"链 2048 / 分区 4096"的真实形态）、`chain.key_file_missing`。

**契约**

- `tests/contract/test_cli_json_schema.py`（新，可选）：锁定各命令 `--json` 的顶层键集合，防止包装脚本被无声破坏。

**约束**：测试一律用 `tmp_path` + `FakeAvbTool`，不得读写真实 `Keys/` / `Images/` / `profiles/`。

---

## 7. 验收标准（DoD）

1. 下列流程可**零手工改 JSON** 完成：

```shell
# 1+3 一步生成（镜像集合由包装脚本按旗标表算好）
avbpowertool config create --id 20260101-120000_testkey --name testkey `
  --from-images --images boot,dtbo,init_boot,pvmfw,recovery,vendor_boot,vbmeta,vbmeta_system `
  --json

# 1 的密钥部分（如需单独准备）
avbpowertool keys discover --profile 20260101-120000_testkey
avbpowertool keys ensure-public --profile 20260101-120000_testkey

# 4 改链式 / flags / key / algorithm / 剪枝
avbpowertool config edit vbmeta --profile 20260101-120000_testkey --set flags=1 `
  --append chain_partitions=boot:3:testkey_rsa4096.pem.bin `
  --append chain_partitions=recovery:1:testkey_rsa4096.pem.bin `
  --append chain_partitions=vbmeta_system:2:testkey_rsa2048.pem.bin
avbpowertool config edit vbmeta_system --profile 20260101-120000_testkey `
  --set key_id=testkey_rsa2048 --set algorithm=SHA256_RSA2048
avbpowertool config edit vbmeta --profile 20260101-120000_testkey --remove included_partitions=odm

# 校验与改名、导出
avbpowertool config check-chains --profile 20260101-120000_testkey --json
avbpowertool config rename 20260101-120000_testkey my_testkey_config
avbpowertool config export my_testkey_config --output my_testkey_config.zip --json
```

2. `config show --json` / `image sign --dry-run` 在不带 `--profile` 时对活动配置生效。
3. 所有新命令 `--json` 输出可被 PowerShell `ConvertFrom-Json` 直接消费；错误以非 0 退出码 + `issues[].error_code` 表达。
4. `uv run pytest tests/`、`ruff check`、`ruff format --check`、`pyright` 全绿。
5. `docs/zh` 与 `docs/en` 同步更新（命令面、错误码表、BACKEND_API 用例清单）。

---

## 8. 未决问题（实现前需确认）

| # | 问题 | 影响 | 作答 |
|---|---|---|---|
| Q1 | 镜像头部算法为 `NONE` 的分区（实测 `dtbo`/`init_boot`/`pvmfw`/`vendor_boot`），步骤 4 的"换 key"是否应同时把 `algorithm` 改为 `SHA256_RSA4096`？ | 决定包装脚本是"只改 key_id"（NONE 下是空操作）还是"key+algorithm 一起改" | 这些分区的算法保持 NONE |
| Q2 | "剪掉 `--include_descriptors_from_image` 条目"指配置里的 `included_partitions`（分区名，签名时转成该参数），还是字面字段 `include_descriptors_from_image`（镜像文件名，目前无生产者自动填）？ | 决定 P1-2/P0-2 的剪枝实现位置 | 剪掉 `included_partitions` |
| Q3 | `chain_partitions` 硬编码三条是"整组替换"还是"按分区名合并（保留镜像读回的其它链）"？ | 决定 `--append` 语义是否够用，或需要 `--set` 替换语义 | 按照分区名合并 |
| Q4 | `--core/--mi/--oplus` 的 hashtree 分区是否需要还原原始 `partition_size`？`info_image` 无法读出该值 | 决定是否要新增 `--partition-size PART=SIZE` 之类的外部输入通道 | 不需要还原原始分区大小 |

---

## 附录 A · 现有可用能力（脚本今天就能用的部分）

- `avbpowertool image inspect <imgs> --json`：**唯一不依赖 profile 的 CLI 能力**，输出 `descriptor/algorithm/flags/salt/rollback_index/props/included_partitions/chain_partitions(含 public_key_sha1)`，可直接喂给 PowerShell。
- `avbpowertool config list --json`、`config activate`、`config export <id> --output`：均实测可用；导出 zip 内容为 `manifest.json` + `profile.json` + `keys/**`（含 `.pem` 与 `.pem.bin`），不含镜像。
- Python API：`bootstrap()` / `InspectImagesUseCase` / `SignImagesUseCase` / `KeyDiscoveryUseCase` / `ensure_public_keys()` / `ResolveChainKeysUseCase` / `ProfileRepository` / `ConfigExportUseCase` 可直接调用（`docs/zh/BACKEND_API.md`）。
- 直接调 vendor：`uv run python avbtool.py extract_public_key --key <pem> --output <pem>.bin`（已实测）。

## 附录 B · 实测证据（本仓库 HEAD，Windows / Python 3.13）

```
$ uv run avbpowertool config list --json          -> exit 0，列出 tb710fu-470-no-ubl（active）
$ uv run avbpowertool config show --json          -> exit 1，config.not_found: Profile not found: current
$ uv run avbpowertool image sign boot --dry-run   -> exit 1，同上
$ uv run avbpowertool config edit boot --profile tb710fu-470-no-ubl --set key_id=testkey_rsa2048
    -> config.invalid_field: Field 'key_id' is not editable via config edit
$ uv run avbpowertool config edit vbmeta_system --profile tb710fu-470-no-ubl --set algorithm=SHA256_RSA2048
    -> config.invalid_field: Field 'algorithm' is not editable via config edit
$ uv run avbpowertool config edit vbmeta --profile tb710fu-470-no-ubl --set chain_partitions=... --set flags=1
    -> exit 0（写入成功，随后已还原原文件）
$ uv run avbpowertool config export tb710fu-470-no-ubl --output <tmp>.zip
    -> exit 0；zip: manifest.json, keys/manifest.json, keys/testkey_rsa2048.pem(.bin),
       keys/testkey_rsa4096.pem(.bin), profile.json
$ uv run avbpowertool image inspect vbmeta vbmeta_system --json
    -> vbmeta: included=[dtbo,init_boot,vendor_boot,odm,system_dlkm,vendor,vendor_dlkm]
               chains=[boot:3,recovery:1,vbmeta_system:2]（公钥 sha1 均为 OEM 8fcb864f…）
    -> vbmeta_system: included=[pvmfw,product,system,system_ext]
```

> 注：`tests/conftest.py:89-121` 的 `tmp_workspace` 恰好创建了一个**真名为 `current`** 的 profile，
> 因此"`current` 不解析"这个缺陷在测试中从未暴露。P0-1 的"字面优先"规则既修复缺陷，又保持该 fixture 可用。
