# 密钥管理

AVBPowerTool2 中签名密钥的工作原理及设置方法。

## 密钥解析机制

当 AVBPowerTool2 签名镜像时，需要为每个分区的 `key_id` 找到对应的私钥文件。解析链如下：

```
profile.json 中分区的 key_id
    -> keys/manifest.json 查找
        -> keys/<文件名>.pem 读取磁盘文件
```

### 详细步骤：

1. 配置的 `profile.json` 中每个分区包含一个 `key_id`（如 `"key_id": "release_rsa4096"`）。
2. 工具读取 `keys/manifest.json` 并查找该 `key_id`。
3. manifest 条目将 key_id 映射到 `.pem` 文件名（如 `"release_rsa4096.pem"`）。
4. 工具解析路径为 `profiles/<profile>/keys/<文件名>.pem`。

如果任何步骤失败，签名会报告 `config.key_missing` 错误。

## manifest.json 格式

```json
{
  "release_rsa4096": {
    "private_key": "release_rsa4096.pem",
    "public_key": "release_rsa4096_pub.bin"
  },
  "test_rsa2048": {
    "private_key": "test_rsa2048.pem"
  }
}
```

- **key_id**（字典键）：被 `profile.json` 分区引用的稳定标识符。
- **private_key**（必需）：`keys/` 目录中 `.pem` 私钥文件的文件名。
- **public_key**（可选）：已提取的公钥二进制文件名。

## 设置密钥

### 方法一：自动发现（推荐新配置使用）

1. 将 `.pem` 文件放入配置的 `keys/` 目录：

```
profiles/my_device/keys/
  release_rsa4096.pem
  test_rsa2048.pem
```

2. 通过 TUI（`配置管理器 > 管理密钥 > 自动发现密钥`）或 API 运行自动发现：

```python
from avbpowertool.application.commands import KeyDiscoveryRequest
from avbpowertool.application.services.manage_keys import KeyDiscoveryUseCase

uc = KeyDiscoveryUseCase(ws)
result = uc.execute(KeyDiscoveryRequest(profile_id="my_device"))
print(f"发现了 {result.discovered_count} 个密钥")
for key_id, filename in result.manifest_entries:
    print(f"  {key_id} -> {filename}")
```

3. **自动发现的命名规则**：每个 `.pem` 文件名（去掉 `.pem` 后缀）成为 `key_id`。例如：
   - `release_rsa4096.pem` -> key_id `release_rsa4096`
   - `test.pem` -> key_id `test`
   - `my_custom_key.pem` -> key_id `my_custom_key`

4. **重要**：`profile.json` 中的 `key_id` 必须与 manifest 中的 key_id 匹配。如果重命名了 `.pem` 文件，必须重新运行自动发现或手动更新 manifest。

### 方法二：手动设置

1. 将 `.pem` 文件放入 `profiles/<profile>/keys/`。

2. 创建或编辑 `profiles/<profile>/keys/manifest.json`：

```json
{
  "my_key_id": {
    "private_key": "any_filename.pem"
  }
}
```

key_id 不需要与文件名匹配，可以使用任何稳定的标识符。

3. 在 `profile.json` 中引用该 key_id：

```json
{
  "key_id": "my_key_id",
  "partition_name": "boot"
}
```

### 方法三：TUI 密钥管理

在 TUI 中导航到 `配置管理器 > 管理密钥`。从那里可以：

- **列出密钥**：查看所有已注册的密钥（来自 manifest）和磁盘上未注册的 `.pem` 文件。
- **自动发现密钥**：扫描 `keys/` 目录中的 `.pem` 文件并重建 manifest（文件名 = key_id）。
- **手动添加密钥**：指定 key_id 和文件名。当文件名与所需的 key_id 不同时很有用。
- **移除密钥**：从 manifest 中删除条目（不会删除 `.pem` 文件）。

## 目录结构

```
profiles/my_device/
  profile.json          # v2 配置，每个分区引用 key_id
  keys/
    manifest.json       # key_id -> 文件名映射
    release.pem         # PEM 私钥文件
    test.pem
    release_pub.bin     # 可选：已提取的公钥
```

## 密钥文件要求

- 密钥必须是 PEM 格式的 RSA 私钥。
- 密钥大小必须与签名算法匹配：
  - `SHA256_RSA2048` / `SHA512_RSA2048` -> 2048 位 RSA 密钥
  - `SHA256_RSA4096` / `SHA512_RSA4096` -> 4096 位 RSA 密钥
  - `SHA256_RSA8192` / `SHA512_RSA8192` -> 8192 位 RSA 密钥
- 密钥默认不包含在配置归档中（使用 `config export` 可包含）。

## 故障排除

| 错误 | 含义 | 修复方法 |
|---|---|---|
| `config.key_missing` | manifest 中找不到 key_id | 运行自动发现或手动添加密钥 |
| `keys.manifest_not_found` | `manifest.json` 不存在 | 运行自动发现 |
| `keys.file_not_found` | manifest 引用的 `.pem` 文件不存在 | 将文件放入 `keys/` 或修复 manifest |
| `keys.directory_not_found` | `keys/` 目录不存在 | 创建目录：`mkdir -p profiles/<id>/keys` |

## API 参考

```python
from avbpowertool.application.services.manage_keys import (
    KeyListUseCase,        # 列出配置中的密钥
    KeyDiscoveryUseCase,   # 自动发现 .pem 文件
    KeyAddUseCase,         # 手动添加密钥条目
    KeyRemoveUseCase,      # 移除密钥条目
)
```
