# 后端 API 参考

在 Python 中直接调用 AVBPowerTool2 后端，无需通过 CLI 或 TUI。

## 安装

```python
from avbpowertool.bootstrap import bootstrap
```

## 快速开始

```python
from pathlib import Path
from avbpowertool.bootstrap import bootstrap
from avbpowertool.infrastructure.avbtool.runner import SubprocessAvbTool
from avbpowertool.application.commands import InspectImagesRequest, SignImagesRequest
from avbpowertool.application.services.inspect_images import InspectImagesUseCase
from avbpowertool.application.services.sign_images import SignImagesUseCase

# 初始化工作区
ws = bootstrap(root=Path("/path/to/project"))
avb = SubprocessAvbTool(ws.avbtool_script)

# 检查镜像
uc = InspectImagesUseCase(ws, avb)
result = uc.execute(InspectImagesRequest(image_names=("boot", "vbmeta")))
for img in result.images:
    print(f"{img.image_name}: {img.descriptor}, {img.algorithm}")

# 签名镜像（dry-run）
uc = SignImagesUseCase(ws, avb)
result = uc.execute(SignImagesRequest(image_names=("boot",), dry_run=True))
print(f"计划: {len(result.plan.steps)} 个步骤")
```

## 工作区 (Workspace)

```python
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths

# 从当前目录自动发现
ws = WorkspacePaths.discover()

# 指定根目录
ws = WorkspacePaths.discover(Path("/my/project"))

# 关键路径
ws.root                        # Path: 项目根目录
ws.profiles                    # Path: profiles/ 目录
ws.resolve_profile_dir("test") # Path: profiles/test/
ws.resolve_key_dir("test")     # Path: profiles/test/keys/
ws.staging                     # Path: .avbpowertool-staging/
ws.avbtool_script              # Path: avbtool.py
ws.ensure_dirs()               # 创建运行时目录
```

## 用例 (Use Cases)

### InspectImagesUseCase

从镜像文件读取 AVB 元数据。

```python
from avbpowertool.application.commands import InspectImagesRequest

uc = InspectImagesUseCase(ws, avb)
result = uc.execute(InspectImagesRequest(
    image_names=("boot", "system", "vbmeta"),
    profile_id="current",  # 可选，默认 "current"
))

# 结果
result.images   # tuple[ImageInspection, ...]
result.issues   # tuple[OperationIssue, ...]
```

**ImageInspection 字段：**
- `image_name: str` — 逻辑名称
- `image_path: str` — 解析后的路径
- `descriptor: DescriptorType | None` — HASH、HASHTREE、VBMETA 或 None
- `algorithm: str | None` — 如 "SHA256_RSA4096"
- `partition_name: str | None`
- `public_key_sha1: str | None`
- `rollback_index: str | None`
- `salt: str | None`
- `digest: str | None`
- `flags: str | None`
- `props: tuple[tuple[str, str], ...]`
- `raw_extensions: tuple[tuple[str, str], ...]`

### SignImagesUseCase

带 staging 和原子替换的镜像签名。

```python
from avbpowertool.application.commands import SignImagesRequest

uc = SignImagesUseCase(ws, avb)

# Dry-run（仅生成计划）
result = uc.execute(SignImagesRequest(
    image_names=("boot", "vbmeta"),
    profile_id="current",
    dry_run=True,
))

# 执行签名
result = uc.execute(SignImagesRequest(
    image_names=("boot", "vbmeta"),
    profile_id="current",
    dry_run=False,
    remove_existing_footers=False,
))

# 结果
result.plan           # SigningPlan
result.executed       # bool
result.success_count  # int
result.fail_count     # int
result.issues         # tuple[OperationIssue, ...]
```

**SigningPlan 字段：**
- `profile_id: str`
- `steps: tuple[SigningStep, ...]`
- `vbmeta_order: tuple[str, ...]`
- `issues: tuple[OperationIssue, ...]`

**SigningStep 字段：**
- `partition_name: str`
- `operation: str` — "add_hash_footer"、"add_hashtree_footer"、"make_vbmeta_image"
- `command: tuple[str, ...]` — avbtool 参数列表
- `input_path: str`
- `output_path: str`
- `order: int`

### ConfigShowUseCase

显示当前活动配置。

```python
from avbpowertool.application.commands import ConfigShowRequest

uc = ConfigShowUseCase(ws)
result = uc.execute(ConfigShowRequest(profile_id="current"))

result.config_name  # str
result.partitions   # tuple[PartitionConfig, ...]
result.issues       # tuple[OperationIssue, ...]
```

### ConfigValidateUseCase

验证配置与工作区镜像和密钥的一致性。

```python
from avbpowertool.application.commands import ConfigValidateRequest

uc = ConfigValidateUseCase(ws)
result = uc.execute(ConfigValidateRequest(profile_id="current"))

result.missing_images  # tuple[str, ...]
result.missing_keys    # tuple[str, ...]
result.issues          # tuple[OperationIssue, ...]
```

### ConfigImportUseCase / ConfigExportUseCase

```python
from avbpowertool.application.commands import ConfigImportRequest, ConfigExportRequest

# 导入
uc = ConfigImportUseCase(ws)
result = uc.execute(ConfigImportRequest(archive_path="/path/to/archive.zip"))
result.profile_id  # str

# 导出
uc = ConfigExportUseCase(ws)
result = uc.execute(ConfigExportRequest(
    profile_id="myprofile",
    output_path="/path/to/output.zip",  # 可选
))
result.output_path  # str
```

### ProfileListUseCase / ProfileActivateUseCase

```python
from avbpowertool.application.commands import ProfileListRequest, ProfileActivateRequest

# 列出
uc = ProfileListUseCase(ws)
result = uc.execute(ProfileListRequest())
for p in result.profiles:
    print(f"{p.profile_id}: {p.name} (active={p.is_active}, {p.partition_count} partitions)")

# 激活
uc = ProfileActivateUseCase(ws)
result = uc.execute(ProfileActivateRequest(profile_id="myprofile"))
```

### KeyDiscoveryUseCase

发现 .pem 文件并更新 manifest。

```python
from avbpowertool.application.commands import KeyDiscoveryRequest

uc = KeyDiscoveryUseCase(ws)
result = uc.execute(KeyDiscoveryRequest(profile_id="current"))

result.discovered_count   # int
result.manifest_entries   # tuple[tuple[str, str], ...]  (key_id, filename)
```

`KeyDiscoveryRequest(merge=True)`（默认）保留已有的 `public_key` /
`public_key_sha1` 缓存（仅当条目仍指向同一个 `private_key` 文件名）；
`merge=False`（CLI 的 `--replace`）完全重建 manifest 并丢弃缓存。
结果里还有 `retained_count`（保留的、没有对应 `.pem` 的条目数）与 `merged`。

### KeyEnsurePublicUseCase

生成缺失的公钥文件（`<private_key>.pem.bin`）并把 `public_key` 回写 manifest。
需要 `AvbToolPort`。

```python
from avbpowertool.application.commands import KeyEnsurePublicRequest
from avbpowertool.application.services.manage_keys import KeyEnsurePublicUseCase

uc = KeyEnsurePublicUseCase(ws, avb)
result = uc.execute(KeyEnsurePublicRequest(profile_id="current"))

result.extracted  # tuple[tuple[str, str], ...]  (key_id, 公钥文件名)
result.skipped    # tuple[str, ...]  私钥文件缺失、被跳过的 key_id
result.issues     # tuple[OperationIssue, ...]
```

### ConfigAutoCreateUseCase

扫描镜像目录 → 逐张 `info_image` → 生成分区配置。**不写盘**；创建向导与
CLI 的 `config create --from-images` 共用。

```python
from avbpowertool.application.commands import ConfigAutoCreateRequest
from avbpowertool.application.services.config_auto_create import ConfigAutoCreateUseCase

uc = ConfigAutoCreateUseCase(ws, avb)
result = uc.execute(ConfigAutoCreateRequest(
    image_dir=ws.images,                 # 必填
    image_names=("boot", "vbmeta"),      # 空 = 目录内全部 *.img（按名排序）
    key_id=None,                         # 覆盖自动 key 选择
    available_keys=("mykey_rsa4096",),   # 自动选择的候选
    default_key_id="default",
    profile_id="current",                # 链解析时用
    resolve_chains=True,
    allow_fallback=True,                 # TUI 历史行为；CLI 传 False
))

result.partitions      # tuple[PartitionConfig, ...]
result.scanned_images  # tuple[str, ...]  扫描到的镜像 stem（已排序）
result.skipped_images  # tuple[str, ...]  无 AVB 结构而被跳过的镜像
result.chain_issues    # tuple[OperationIssue, ...]  链解析问题（不阻断）
result.issues          # tuple[OperationIssue, ...]  inspect 阶段的问题
```

### ConfigCreateFromImagesUseCase

`config create --from-images` 的用例：扫描 → 生成 → **写盘** → 报告缺失密钥。
每个提前返回都**不写盘**。需要 `AvbToolPort`。

```python
from avbpowertool.application.commands import ConfigCreateFromImagesRequest
from avbpowertool.application.services.config_auto_create import ConfigCreateFromImagesUseCase

uc = ConfigCreateFromImagesUseCase(ws, avb)
result = uc.execute(ConfigCreateFromImagesRequest(
    profile_id="my_device",
    profile_name="",                     # 空 -> 用 profile_id
    image_dir=None,                      # None -> 工作区 Images/
    image_names=("boot", "vbmeta"),      # 空 -> 目录内全部 *.img
    key_id=None,
    resolve_chains=True,
    allow_fallback=False,                # CLI 默认；True 恢复向导的“塞入全部”行为
    skip_non_avb=False,                  # False 时无 AVB 结构的镜像致命
    overwrite=False,
    activate=False,                      # 默认不激活
))

result.created          # bool   配置目录是否已写出
result.partition_count  # int
result.chain_count      # int
result.scanned_images   # tuple[str, ...]
result.skipped_images   # tuple[str, ...]
result.missing_keys     # tuple[str, ...]  仅供参考，不影响成功
result.chain_issues     # tuple[OperationIssue, ...]  链解析问题（信息性，不影响成功）
result.issues           # tuple[OperationIssue, ...]  inspect 阶段的问题 + 真正致命的错误
```

`ConfigCreateUseCase` 对应空配置路径，其请求多了
`allow_empty: bool = False` 与 `overwrite: bool = False`。

### ProfileRenameUseCase

```python
from avbpowertool.application.commands import ProfileRenameRequest
from avbpowertool.application.services.manage_profiles import ProfileRenameUseCase

uc = ProfileRenameUseCase(ws)
result = uc.execute(ProfileRenameRequest(
    profile_id="old_id",
    new_profile_id="new_id",   # 与 profile_id 相同 = 只改显示名
    new_name="New name",       # None = 保持原名
))

result.old_profile_id  # str
result.profile_id      # str   新 id
result.renamed         # bool  目录是否真的移动过
result.name_changed    # bool
result.issues          # tuple[OperationIssue, ...]
```

### CheckChainsUseCase

只读的链式一致性校验（需要 `AvbToolPort`：manifest 没有可用 `public_key` 时
用它把公钥提取到 staging 目录，**不写进 key store**）。

```python
from avbpowertool.application.commands import CheckChainsRequest
from avbpowertool.application.services.check_chains import CheckChainsUseCase

uc = CheckChainsUseCase(ws, avb)
result = uc.execute(CheckChainsRequest(profile_id="current"))

result.profile_id  # str
result.checked     # int  检查的链条目数
result.entries     # tuple[ChainCheckEntry, ...]  (partition_name, entry, ok)
result.issues      # tuple[OperationIssue, ...]  含 chain.key_mismatch 等
```

### profile_id 的解析行为

`profile_id` 默认值为 `"current"`，解析顺序（**字面优先**）：

1. `profiles/<profile_id>/profile.json` 存在 → 用字面 id；
2. 请求为 `"current"`/空，且 `.active-profile` 指向一个存在的配置 → 用活动 id；
3. 否则报 `config.no_active_profile`（请求是 current/空）或 `config.not_found`。

受影响用例：`ConfigShowUseCase`、`ConfigValidateUseCase`、`ConfigEditUseCase`、
`ConfigMigrateUseCase`、`SignImagesUseCase`、`CheckChainsUseCase`、
`ResolveChainKeysUseCase`。

**key store 相关用例是宽容的**：`KeyListUseCase` / `KeyDiscoveryUseCase` /
`KeyEnsurePublicUseCase` / `KeyAddUseCase` / `KeyRemoveUseCase` 走
`resolve_key_store_profile_id` —— 同样的「字面优先 + current→活动配置」，但
**非空请求解析失败时按字面值继续**，由用例自己报 `keys.directory_not_found`。
这样创建向导可以先准备好 `profiles/<id>/keys/`、稍后才写 `profile.json`；
只有「空请求 + 没有活动配置」才直接报 `config.no_active_profile`。

## 领域模型

### AvbProfile

```python
from avbpowertool.domain.models import AvbProfile, PartitionConfig, DescriptorType, SigningAlgorithm

profile = AvbProfile(
    id="myprofile",
    name="我的配置",
    schema_version=3,
    key_store_path="keys",
    partitions={
        "boot": PartitionConfig(
            image="boot.img",
            descriptor=DescriptorType.HASH,
            algorithm=SigningAlgorithm.SHA256_RSA4096,
            key_id="release_rsa4096",
            partition_name="boot",
            rollback_index=0,
            salt="abcdef",
            flags=0,
            props=(("key1", "val1"),),
        ),
    },
)
```

### OperationIssue

所有用例返回 `OperationIssue` 元组而非抛出异常。

```python
from avbpowertool.domain.models import OperationIssue

issue = OperationIssue(
    error_code="config.key_missing",
    message="Key 'testkey' not found in manifest",
)
```

## 进度事件

通过 `ProgressSink` 订阅签名进度：

```python
from avbpowertool.application.ports import ProgressSink, ProgressEvent
from avbpowertool.application.events import StepStarted, StepCompleted, SigningCompleted

class MyProgress:
    def on_event(self, event: ProgressEvent) -> None:
        if isinstance(event, StepStarted):
            print(f"正在签名 {event.partition_name}...")
        elif isinstance(event, StepCompleted):
            print(f"  {'成功' if event.success else '失败'}")
        elif isinstance(event, SigningCompleted):
            print(f"完成: {event.success_count} 成功, {event.fail_count} 失败")

uc = SignImagesUseCase(ws, avb, progress=MyProgress())
```

## 直接调用 avbtool

直接使用 `SubprocessAvbTool` 进行原始 avbtool 操作：

```python
from pathlib import Path
from avbpowertool.infrastructure.avbtool.runner import SubprocessAvbTool

avb = SubprocessAvbTool(ws.avbtool_script)

# 检查
result = avb.inspect_image(Path("/images/boot.img"))
print(result.stdout)

# 提取公钥
result = avb.extract_public_key(
    Path("/keys/test.pem"),
    Path("/keys/test_pub.bin"),
)

# 所有方法: inspect_image, erase_footer, add_hash_footer,
# add_hashtree_footer, make_vbmeta_image, extract_public_key
```

## 错误代码

所有用例以 `OperationIssue` 元组返回问题，不抛异常。错误码稳定、点分前缀；
CLI 的退出码映射为：`config.*` / `keys.*` / `image.*` / `chain.*` → 1，
`tool.*` / `signing.*` → 3，未知前缀 → 0。完整清单见
[CLI_REFERENCE.md](CLI_REFERENCE.md#5-错误码清单)。

| 代码 | 含义 |
|---|---|
| `config.not_found` | Profile 或配置未找到 |
| `config.no_active_profile` | 请求 `current`/空，但没有活动配置 |
| `config.parse_error` | 配置格式无效 |
| `config.invalid_profile_id` | profile id 含非法字符 |
| `config.profile_exists` | 同名配置已存在 |
| `config.profile_id_mismatch` | 目录名与 `profile.json` 里的 id 不一致，拒绝写入 |
| `config.no_partitions` | 配置没有任何分区 |
| `config.invalid_field` | 字段不在可编辑白名单，或值非法 |
| `config.invalid_algorithm` | 不是合法签名算法 |
| `config.invalid_option_combination` | 同一字段同时用 `--set/--unset` 与 `--append/--remove`；或选项组合非法 |
| `config.partition_missing` | 分区不在 Profile 中 |
| `config.key_missing` | 密钥文件未找到 / key_id 不在 manifest |
| `config.missing_included_partition` | vbmeta 引用了不在配置里的分区 |
| `config.auto_dir_not_found` | `--from-images DIR` 目录不存在 |
| `config.vbmeta_no_contents` | vbmeta 既无 `included_partitions` 也无 `chain_partitions` |
| `config.invalid_schema_version` | Schema 版本错误 |
| `config.save_failed` / `config.rename_failed` / `config.activate_failed` | 对应写盘操作失败 |
| `config.invalid_archive` | 归档格式非法 |
| `image.not_found` | 镜像文件未找到 |
| `image.no_vbmeta_structure` | 镜像无 AVB footer |
| `chain.malformed_entry` | 链条目不是合法三元组 |
| `chain.key_file_missing` | 链条目公钥文件不在 key store |
| `chain.key_mismatch` | 链条目公钥 ≠ 被链分区实际签名密钥 |
| `chain.chained_partition_unsigned` | 被链分区是 NONE（未签名） |
| `chain.key_not_found` | 链解析时没有密钥匹配描述符的公钥 SHA1 |
| `signing.step_failed` | 签名步骤失败 |
| `tool.execution_failed` | avbtool 返回非零 |
| `keys.directory_not_found` | key store 目录不存在 |
| `keys.file_not_found` | `keys add` 指定的私钥文件不存在 |
| `keys.not_found` / `keys.already_exists` | `keys remove` / `keys add` 的 key_id 状态冲突 |
| `keys.private_key_missing` | 条目指向的私钥文件缺失 |
| `keys.public_key_extract_failed` | 公钥提取失败 |
| `keys.manifest_not_found` | 密钥 manifest 缺失 |
| `workspace.path_escape` | 路径逃逸出工作区 |
