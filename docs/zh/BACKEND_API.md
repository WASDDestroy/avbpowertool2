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

## 领域模型

### AvbProfile

```python
from avbpowertool.domain.models import AvbProfile, PartitionConfig, DescriptorType, SigningAlgorithm

profile = AvbProfile(
    id="myprofile",
    name="我的配置",
    schema_version=2,
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

| 代码 | 含义 |
|---|---|
| `config.not_found` | Profile 或配置未找到 |
| `config.parse_error` | 配置格式无效 |
| `config.key_missing` | 密钥文件未找到 |
| `config.partition_missing` | 分区不在 Profile 中 |
| `config.invalid_schema_version` | Schema 版本错误 |
| `image.not_found` | 镜像文件未找到 |
| `image.no_vbmeta_structure` | 镜像无 AVB footer |
| `signing.step_failed` | 签名步骤失败 |
| `tool.execution_failed` | avbtool 返回非零 |
| `keys.manifest_not_found` | 密钥 manifest 缺失 |
| `workspace.path_escape` | 路径逃逸出工作区 |
