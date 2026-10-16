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
- **public_key**（可选）：已提取的公钥二进制文件名（`extract_public_key` 产物，
  通常形如 `<private_key>.pem.bin`）。
- **public_key_sha1**（可选）：缓存的公钥 SHA1，用于链式分区匹配。
  `keys discover --merge` 只在该条目仍指向同一个 `private_key` 文件名时保留这两个
  缓存字段；`--replace` 会全部丢弃。

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

### 方法四：CLI（`keys` 子命令）

```shell
avbpowertool keys list          [--profile ID] [--json]
avbpowertool keys discover      [--profile ID] [--merge|--replace] [--json]
avbpowertool keys ensure-public [--profile ID] [--json]
avbpowertool keys add    <KEY_ID> --file <NAME.pem> [--profile ID] [--json]
avbpowertool keys remove <KEY_ID> [--profile ID] [--json]
```

- `--profile` 默认 `current`：先按字面 id 找，找不到且请求是 `current`/空时解析为
  `.active-profile` 指向的活动配置（key store 用例对非空请求采用宽容解析：
  解析不到就按字面值继续，由用例报 `keys.directory_not_found`）。
- **`keys list`**：列出 manifest 中已注册的密钥，以及磁盘上**尚未注册**的 `.pem`。
- **`keys discover`**：扫描 `keys/` 里的 `.pem`，以「文件名去掉 `.pem`」为 key_id
  写入 `manifest.json`。
  - `--merge`（**默认**）：以磁盘上已有的 manifest 为基线。每个发现的 `.pem` 更新
    自己条目的 `private_key`；缓存的 `public_key` / `public_key_sha1` **仅在该条目
    仍指向同一个私钥文件名时**保留（换了文件说明缓存属于另一把密钥）。磁盘上已没有
    对应 `.pem` 的条目**原样保留**，不会被删掉。
  - `--replace`：旧的历史行为 —— manifest 完全由发现的 `.pem` 重建，
    **所有缓存的 `public_key` 都被丢弃**。需要重新提取公钥时再跑 `ensure-public`。
- **`keys ensure-public`**：为 manifest 中每个条目生成缺失的公钥文件
  （`avbtool extract_public_key` 输出为 `<私钥文件名>.pem.bin`，或条目里已有的
  `public_key` 名字），并把 `public_key` 回写进 manifest。私钥文件缺失的条目会被
  跳过并报 `keys.private_key_missing`；提取失败报
  `keys.public_key_extract_failed`。
- **`keys add <KEY_ID> --file <NAME.pem>`**：往 manifest 加一条映射。
  `--file` 是 **key store 目录内**的私钥文件名，**不会**从别处复制文件。
- **`keys remove <KEY_ID>`**：从 manifest 删除条目（**不删除 `.pem` 文件**）。

```shell
# 典型流程：放入 .pem -> 发现 -> 生成公钥
avbpowertool keys discover      --profile my_device --json
avbpowertool keys ensure-public --profile my_device --json
avbpowertool keys list          --profile my_device
```

完整参数与 `--json` 输出键见 [CLI_REFERENCE.md](CLI_REFERENCE.md#keys-子命令)。

## 目录结构

```
profiles/my_device/
  profile.json          # v3 配置，每个分区引用 key_id
  keys/
    manifest.json       # key_id -> 文件名映射
    release.pem         # PEM 私钥文件
    test.pem
    release.pem.bin     # 可选：已提取的公钥（extract_public_key 产物）
```

## 密钥文件要求

- 密钥必须是 PEM 格式的 RSA 私钥。
- 密钥大小必须与签名算法匹配：
  - `SHA256_RSA2048` / `SHA512_RSA2048` -> 2048 位 RSA 密钥
  - `SHA256_RSA4096` / `SHA512_RSA4096` -> 4096 位 RSA 密钥
  - `SHA256_RSA8192` / `SHA512_RSA8192` -> 8192 位 RSA 密钥
- 密钥默认不包含在配置归档中（使用 `config export` 可包含）。

## 链式分区的公钥文件（重要）

vbmeta 的链式分区条目写成 `PART:SLOT:KEYFILE` 三元组，其中 `KEYFILE` 是
**公钥文件**，相对 key store（`profiles/<id>/keys/`）解析。

**`KEYFILE` 必须是 `extract_public_key` 的产物**（`*.pem.bin`），
也就是 `keys ensure-public` 生成的、或手工执行
`avbtool extract_public_key --key <name>.pem --output <name>.pem.bin` 得到的文件。
原因是 avbtool 在 `--chain_partition` 里把第三段当作**原始字节**直接读入并嵌入
vbmeta：传一个 PEM 文本文件进去会写坏 vbmeta（链公钥与真实公钥不一致，
校验时必然失败）。`keys discover` / `keys ensure-public` 默认就把公钥写到
`<name>.pem.bin`，直接引用即可：

```json
{
  "key_id": "mykey_rsa4096",
  "private_key": "mykey_rsa4096.pem",
  "public_key": "mykey_rsa4096.pem.bin"
}
```

```
chain_partitions: ["vbmeta_system:2:mykey_rsa2048.pem.bin"]   # 正确
chain_partitions: ["vbmeta_system:2:mykey_rsa2048.pem"]       # 错误：会写坏 vbmeta
```

**用 `config check-chains` 发现不一致。** 这条命令只读，会遍历配置里每条
`chain_partitions`，逐条检查：分区是否存在、被链分区是否未签名（NONE）、
公钥文件是否存在、以及**链条目公钥的 SHA1 是否等于被链分区实际签名密钥的公钥
SHA1** —— 最后一项不等时报 `chain.key_mismatch`，正是「链条目公钥与实际签名密钥
不一致」的检测点（本仓库的真实配置当前就命中这一条）：

```shell
$ avbpowertool config check-chains --profile my_device --json
{
  "profile_id": "my_device",
  "checked": 3,
  "issues": [
    {
      "error_code": "chain.key_mismatch",
      "message": "Partition 'vbmeta': chain entry 'vbmeta_system:2:mykey_rsa2048.pem.bin' uses 'mykey_rsa2048.pem.bin' (sha1 cdbb7717...), but 'vbmeta_system' is signed with key id 'mykey_rsa4096' (public key 'mykey_rsa4096.pem.bin', sha1 2597c218...)"
    }
  ]
}
```

修复方式就是让两者一致：要么把被链分区的 `key_id` 换成与链条目匹配的密钥
（`config edit <PART> --set key_id=... --set algorithm=...`），要么把链条目换成
该分区实际使用的公钥文件（`config edit <vbmeta> --append chain_partitions=PART:SLOT:KEYFILE`，
按分区名原地替换）。

## 故障排除

| 错误 | 含义 | 修复方法 |
|---|---|---|
| `config.key_missing` | manifest 中找不到 key_id | 运行自动发现或手动添加密钥 |
| `keys.manifest_not_found` | `manifest.json` 不存在 | 运行自动发现 |
| `keys.file_not_found` | manifest 引用的 `.pem` 文件不存在 | 将文件放入 `keys/` 或修复 manifest |
| `keys.directory_not_found` | `keys/` 目录不存在 | 创建目录：`mkdir -p profiles/<id>/keys` |
| `keys.already_exists` | `keys add` 的 key_id 已在 manifest 中 | 换一个 key_id，或先 `keys remove` |
| `keys.not_found` | `keys remove` 的 key_id 不在 manifest 中 | 用 `keys list` 查看实际条目 |
| `keys.private_key_missing` | `ensure-public` 时条目指向的私钥文件缺失 | 把 `.pem` 放回 `keys/`，或 `keys remove` 该条目 |
| `keys.public_key_extract_failed` | 公钥提取失败（私钥损坏 / 不是 RSA PEM） | 检查私钥格式，或手工跑 `avbtool extract_public_key` |
| `chain.key_file_missing` | 链条目指向的公钥文件不在 key store | 运行 `keys ensure-public`，或修正链条目里的文件名 |
| `chain.key_mismatch` | 链条目公钥与被链分区实际签名密钥不是同一把 | 见上文「链式分区的公钥文件」 |
| `chain.malformed_entry` | 链条目不是 `PART:SLOT:KEYFILE`（SLOT 需为 ≥1 的数字） | 用完整三元组重写该条目 |

## API 参考

```python
from avbpowertool.application.services.manage_keys import (
    KeyListUseCase,        # 列出配置中的密钥
    KeyDiscoveryUseCase,   # 自动发现 .pem 文件（merge / replace）
    KeyEnsurePublicUseCase,# 生成缺失的公钥文件并回写 manifest
    KeyAddUseCase,         # 手动添加密钥条目
    KeyRemoveUseCase,      # 移除密钥条目
)
```

`KeyDiscoveryUseCase` 的合并语义由 `KeyDiscoveryRequest(merge=...)` 控制
（默认 `True`）；`KeyEnsurePublicUseCase` 需要 `AvbToolPort`，返回
`KeyEnsurePublicResult(extracted, skipped, issues)`。请求/结果字段与最小示例见
[BACKEND_API.md](BACKEND_API.md)。
