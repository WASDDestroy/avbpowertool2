# 创建配置

如何创建新的 AVB 签名配置（Profile）。

## 概述

一个配置（Profile）定义了 AVB 镜像的签名方式。它包含：
- 配置 ID 和显示名称
- 一个或多个分区配置（镜像、描述符类型、算法、密钥等）
- 关联的密钥库（`keys/` 目录，包含 PEM 文件和 manifest）

## 快速开始

### 使用 TUI（交互式）

```shell
avbpowertool
# 导航到：配置管理器 > 创建配置
# 按照向导提示操作
```

向导将引导你完成：
1. **配置 ID** — 唯一标识符（如 `my_device`）
2. **配置名称** — 显示名称（如 "我的设备 ROM"）
3. **分区** — 添加一个或多个分区及其签名设置

### 使用 API（Python）

```python
from pathlib import Path
from avbpowertool.bootstrap import bootstrap
from avbpowertool.application.commands import ConfigCreateRequest
from avbpowertool.application.services.manage_configs import ConfigCreateUseCase
from avbpowertool.domain.models import PartitionConfig, DescriptorType, SigningAlgorithm

ws = bootstrap(root=Path("/path/to/project"))
uc = ConfigCreateUseCase(ws)

result = uc.execute(ConfigCreateRequest(
    profile_id="my_device",
    profile_name="我的设备 ROM",
    partitions=(
        PartitionConfig(
            image="boot.img",
            descriptor=DescriptorType.HASH,
            algorithm=SigningAlgorithm.SHA256_RSA4096,
            key_id="release_rsa4096",
            partition_name="boot",
        ),
        PartitionConfig(
            image="vbmeta.img",
            descriptor=DescriptorType.VBMETA,
            algorithm=SigningAlgorithm.SHA256_RSA4096,
            key_id="release_rsa4096",
            partition_name="vbmeta",
            included_partitions=("boot",),
        ),
    ),
    activate=True,
))

if result.issues:
    for iss in result.issues:
        print(f"[{iss.error_code}] {iss.message}")
else:
    print(f"配置已创建: {result.profile_id}")
```

## 创建配置后的步骤

### 1. 放置镜像文件

将 `.img` 文件复制到配置目录：

```
profiles/my_device/
  boot.img
  vbmeta.img
```

### 2. 放置密钥文件

将 PEM 私钥文件复制到配置的 `keys/` 目录：

```
profiles/my_device/keys/
  release_rsa4096.pem
```

然后将密钥注册到 manifest 中。**自动发现**是最简单的方式 — 它扫描 `keys/` 中的所有 `.pem` 文件，并使用文件名（去掉 `.pem`）作为 `key_id`。例如，`release_rsa4096.pem` 对应 key_id `release_rsa4096`。

**通过 TUI**：导航到 `配置管理器 > 管理密钥 > 自动发现密钥`。

**通过 API**：

```python
from avbpowertool.application.commands import KeyDiscoveryRequest
from avbpowertool.application.services.manage_keys import KeyDiscoveryUseCase

uc = KeyDiscoveryUseCase(ws)
result = uc.execute(KeyDiscoveryRequest(profile_id="my_device"))
print(f"发现了 {result.discovered_count} 个密钥")
for key_id, filename in result.manifest_entries:
    print(f"  {key_id} -> {filename}")
```

**重要**：`profile.json` 中分区的 `key_id` 必须与 manifest 中的 key_id 匹配。如果使用自动发现，请将 `.pem` 文件命名为与配置创建时指定的 key_id 一致（如 key_id `release_rsa4096` 对应文件名 `release_rsa4096.pem`）。

关于密钥管理的完整说明（手动设置、manifest 格式、故障排除），请参阅 [KEY_MANAGEMENT.md](KEY_MANAGEMENT.md)。

### 3. 验证

```python
from avbpowertool.application.commands import ConfigValidateRequest
from avbpowertool.application.services.manage_configs import ConfigValidateUseCase

uc = ConfigValidateUseCase(ws)
result = uc.execute(ConfigValidateRequest(profile_id="my_device"))

if result.missing_images:
    print(f"缺失镜像: {result.missing_images}")
if result.missing_keys:
    print(f"缺失密钥: {result.missing_keys}")
```

### 4. 签名

```shell
avbpowertool image sign boot vbmeta --dry-run  # 预览
avbpowertool image sign boot vbmeta --execute --yes  # 执行
```

## 分区类型

### Hash 分区

用于小型镜像（boot、init_boot、dtbo）。使用 `add_hash_footer`。

```python
PartitionConfig(
    image="boot.img",
    descriptor=DescriptorType.HASH,
    algorithm=SigningAlgorithm.SHA256_RSA4096,
    key_id="my_key",
    partition_name="boot",
    rollback_index=0,
    salt="optional_hex_salt",
)
```

### Hashtree 分区

用于大型镜像（system、vendor、product）。使用 `add_hashtree_footer`，带 dm-verity 和 FEC。

```python
PartitionConfig(
    image="system.img",
    descriptor=DescriptorType.HASHTREE,
    algorithm=SigningAlgorithm.SHA256_RSA4096,
    key_id="my_key",
    partition_name="system",
    data_block_size=4096,
    hash_block_size=4096,
)
```

### VBMeta 分区

元分区，包含其他镜像的描述符。使用 `make_vbmeta_image`。

```python
PartitionConfig(
    image="vbmeta.img",
    descriptor=DescriptorType.VBMETA,
    algorithm=SigningAlgorithm.SHA256_RSA4096,
    key_id="my_key",
    partition_name="vbmeta",
    included_partitions=("boot", "system"),
    chain_partitions=("vbmeta_system:1:system_key.pem",),
)
```

## 配置目录结构

创建后，配置目录如下：

```
profiles/my_device/
  profile.json        # v2 配置 schema
  keys/
    manifest.json     # key_id -> 文件名映射
    release.pem       # 密钥文件（需要你添加）
  boot.img            # 镜像文件（需要你添加）
  vbmeta.img
```

## 配置 v2 Schema 参考

```json
{
  "schema_version": 2,
  "profile": {
    "id": "my_device",
    "name": "我的设备 ROM"
  },
  "key_store_path": "keys",
  "partitions": {
    "boot": {
      "image": "boot.img",
      "descriptor": "hash",
      "algorithm": "SHA256_RSA4096",
      "key_id": "release_rsa4096",
      "partition_name": "boot",
      "rollback_index": 0,
      "salt": "",
      "flags": 0,
      "props": []
    }
  }
}
```
