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
3. **选择创建模式** — 手动或自动
4. **准备密钥**（手动/自动共用，在收集镜像**之前**）— 向导创建密钥库目录
   `profiles/<id>/keys/`，提示你把 `.pem` 私钥放入该目录，然后自动发现
   （文件名去掉 `.pem` 即 key_id）。手动模式下 key_id 可直接从发现的密钥中
   选择；自动模式下链式分区的公钥解析有已填充的 manifest 可匹配。
5. **分区** — 添加一个或多个分区及其签名设置

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

### 使用 CLI

`config create` 有两条**互斥**的创建路径（同时给 `--from-images` 和
`--allow-empty` 会被 argparse 拒绝，退出码 2）。

#### 空配置：`--allow-empty`

```shell
avbpowertool config create --id my_device --allow-empty
avbpowertool config create --id my_device --name "我的设备 ROM" --allow-empty --json
```

落盘 `profiles/<id>/profile.json`（无分区）与 `profiles/<id>/keys/`，并在
`keys/manifest.json` **不存在时**写入 `{}`（不会覆盖已经发现的密钥）。同 id 已存在
→ `config.profile_exists`（`--overwrite` 需要 `--from-images`，在本路径上会被拒绝，
退出码 2 且不写盘）。
适合「先建配置 → 放密钥 → 再灌分区」的流程。

#### 从镜像生成：`--from-images`

```shell
# 不带值 = 扫描工作区 Images/ 下全部 *.img
avbpowertool config create --id my_device --from-images --json

# 只处理指定镜像（逗号分隔，可重复；boot 与 boot.img 等价）
avbpowertool config create --id my_device --from-images \
  --images boot,dtbo,init_boot,pvmfw,recovery,vendor_boot,vbmeta,vbmeta_system --json

# 指定扫描目录
avbpowertool config create --id my_device --from-images D:\dump\Images --json
```

行为与失败策略（执行顺序固定，每个提前返回都**不写盘**）：

| 情况 | 结果 |
|---|---|
| `--images` 里**显式请求**的镜像不存在 | `image.not_found`，**不创建配置**（脚本的笔误必须响亮地失败） |
| 镜像没有 AVB 结构 | 默认**致命**：`image.no_vbmeta_structure`，不创建配置；加 `--skip-non-avb` 才跳过，并在结果的 `skipped_images` 里列出 |
| 一个分区都生成不出来 | `config.no_partitions`（想建空配置请用 `--allow-empty`） |
| `profiles/<id>/` 已存在 | `config.profile_exists`；加 `--overwrite` 才复用（保留其 `keys/`，替换分区集合） |
| 链式分区解析不到密钥 | `chain.key_not_found`（退出码 1），但**不阻断创建**，`created` 仍为 `true` |
| 缺少密钥 | 只写进结果的 `missing_keys`，**不影响创建成功** |

`--images` 只过滤扫描集合（镜像集合通常由包装脚本按旗标表算好再传进来）；
`--key KEY_ID` 可以给所有生成的分区指定同一个 key_id（默认按镜像算法自动挑）。

**`--include-fallback`（默认关闭）**：vbmeta 的内嵌描述符在扫描集合里全部被剪空时，
CLI 默认**保留剪空后的结果**；若该 vbmeta 最终既无 `included_partitions` 也无
`chain_partitions`，会报 `config.vbmeta_no_contents`（退出码 1，配置**仍会被创建**）。
加上 `--include-fallback` 才恢复 TUI 向导的历史行为 —— 回退为「其它所有被扫描的
非 vbmeta 分区」。

**激活**：`config create` 默认**不写** `.active-profile`（`--no-activate` 是默认值），
需要时显式给 `--activate`。

> **`--profile current` 现在真的会解析活动配置。** `config show` / `config validate` /
> `config check-chains` / `image sign` / `config edit` / `config migrate` 的 `--profile`
> 默认值是 `current`，解析顺序为：先按字面 id 找 `profiles/<id>/profile.json`；
> 找不到且请求是 `current`/空时，再看 `.active-profile` 指向的活动配置；
> 两者都没有则报 `config.no_active_profile`（退出码 1）。也就是说，一个**真名叫
> `current` 的配置仍然优先**（字面优先，向后兼容）。`config export` / `config rename`
> 不接受 `--profile`，用位置参数显式指定 id。
> 完整规则见 [CLI_REFERENCE.md](CLI_REFERENCE.md#3-profile-与配置解析规则)。

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

**TUI 签名页**：当所选镜像包含 vbmeta 分区时，会额外询问
"是否将此配置中的属性附加到即将生成的 vbmeta 镜像？"，**默认否**。
avbtool 本身不过滤重复属性，自动创建读回的 `com.android.build.*`
等属性通常与子分区重复，默认不写入可避免 vbmeta 体积膨胀和信息冗余；
需要保留时在询问页选择"是"（属性来自该 vbmeta 分区配置的 `props` 字段）。

## 分区类型

### Hash 分区

用于小型镜像（boot、init_boot、dtbo）。使用 `add_hash_footer`。
hash footer 必须指定 `partition_size`（或启用 `dynamic_partition_size`），
否则 avbtool 会拒绝执行。

```python
PartitionConfig(
    image="boot.img",
    descriptor=DescriptorType.HASH,
    algorithm=SigningAlgorithm.SHA256_RSA4096,
    key_id="my_key",
    partition_name="boot",
    partition_size=67108864,      # 必须：分区大小（字节），4096 的整数倍
    rollback_index=0,
    salt="optional_hex_salt",     # 留空则 avbtool 生成随机盐
)
```

### Hashtree 分区

用于大型镜像（system、vendor、product）。使用 `add_hashtree_footer`，带 dm-verity 和 FEC。
v3 起只有一个 `block_size`（默认 4096），不再区分 data/hash 块大小。

```python
PartitionConfig(
    image="system.img",
    descriptor=DescriptorType.HASHTREE,
    algorithm=SigningAlgorithm.SHA256_RSA4096,
    key_id="my_key",
    partition_name="system",
    block_size=4096,              # --block_size（默认 4096）
    fec_num_roots=2,              # --fec_num_roots（默认 2）
    do_not_generate_fec=False,    # 设为 True 则跳过 FEC 生成
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

#### 自动创建时的链式分区与属性

自动创建（扫描目录 → 自动生成配置）时：

- **链式分区**：vbmeta 镜像内嵌的 `Chain Partition` 描述符会被识别为该 vbmeta 的链式分区（而不是混入 `included_partitions`），并尝试还原为 `PART:SLOT:KEY_FILE` 三元组 —— SLOT 取自描述符的 `Rollback Index Location`，KEY_FILE 通过描述符的 `Public key (sha1)` 与密钥清单中每个密钥的 `avbtool extract_public_key` 输出（SHA1）匹配。匹配不到密钥时该链**不会写入配置**，并在结果页给出 `chain.key_not_found` 提示（可之后用 `config edit --set chain_partitions=...` 补齐）。
- **属性（props）**：从镜像读回的属性字符串**保留**在自动生成的配置中（可审查、可手动编辑），但**签名时默认不写入**生成的 vbmeta —— 请在签名确认页选择"是"才会附加（见下文"签名"）。手动创建 vbmeta 分区时也可直接输入属性（逗号分隔的 `key:value`）。
- **已知限制**：`info_image` 输出无法区分 `Chain Partition` 与 `Chain Partition (do not use ab)`，自动创建统一还原为标准 `chain_partitions`；`chain_partitions_do_not_use_ab` 需手动设置。

## 配置目录结构

创建后，配置目录如下：

```
profiles/my_device/
  profile.json        # v3 配置 schema
  keys/
    manifest.json     # key_id -> 文件名映射
    release.pem       # 密钥文件（需要你添加）
  boot.img            # 镜像文件（需要你添加）
  vbmeta.img
```

## 配置 v3 Schema 参考

```json
{
  "schema_version": 3,
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
      "partition_size": 67108864,
      "rollback_index": 0,
      "salt": "",
      "flags": 0,
      "props": []
    }
  }
}
```

## 从 v2 迁移到 v3

v3 的主要变化：hash 分区新增 `partition_size` / `dynamic_partition_size`；
`data_block_size` + `hash_block_size` 合并为 `block_size`；
`kernel_cmdline`（单字符串）改为 `kernel_cmdlines`（字符串数组）；
新增 FEC、`calc_max_image_size`、`output_vbmeta_image`、`use_persistent_digest`、
`chain_partitions_do_not_use_ab`、`padding_size`、`prop_from_file`、
`signing_helper` / `signing_helper_with_files`、`public_key_metadata`、
`append_to_release_string` 等字段。

读取 v2 配置时 AVBPowerTool2 会在内存中自动迁移（v2 文件本身不变）。
要把 v2 文件就地升级为 v3，运行：

```shell
avbpowertool config migrate [--profile ID]
```

### 快速修改单个字段

```shell
# 修改 boot 分区大小、回滚索引、内核 cmdline（逗号分隔）等
avbpowertool config edit boot --profile current \
  --set partition_size=67108864 --set rollback_index=1 \
  --set kernel_cmdlines=androidboot.avb.test=1

# 重置为「空值」（str -> ''、int -> 0、bool -> false、tuple -> ()）
avbpowertool config edit boot --profile my_device --unset salt --unset flags

# 元组字段逐项增删（可重复；先执行全部 --remove，再执行全部 --append）
avbpowertool config edit vbmeta --profile my_device \
  --append included_partitions=system --remove included_partitions=odm
```

**可编辑字段**（白名单之外的字段一律 `config.invalid_field`）：

- 整数：`partition_size`、`rollback_index`、`rollback_index_location`、`flags`、
  `block_size`、`fec_num_roots`、`padding_size`
- 布尔：`dynamic_partition_size`、`do_not_generate_fec`、`calc_max_image_size`、
  `do_not_append_vbmeta_image`、`no_hashtree`、`check_at_most_once`、
  `use_persistent_digest`、`do_not_use_ab`、`set_hashtree_disabled_flag`、
  `set_verification_disabled_flag`、`print_required_libavb_version`、
  `setup_as_rootfs_from_kernel`
- 字符串：`salt`、`hash_algorithm`、`output_vbmeta_image`、
  `setup_rootfs_from_kernel`、`signing_helper`、`signing_helper_with_files`、
  `public_key_metadata`、`append_to_release_string`、**`key_id`**
- 枚举/文件名：**`algorithm`**（非法值 → `config.invalid_algorithm`）、
  **`image`**（必须以 `.img` 结尾）
- 逗号分隔元组：`kernel_cmdlines`、`chain_partitions`、
  `chain_partitions_do_not_use_ab`、`included_partitions`、
  `include_descriptors_from_image`、**`props`**、**`prop_from_file`**
  （`props` / `prop_from_file` 的每一项是 `KEY:VALUE` / `KEY:PATH`）

加粗字段是本轮 CLI 扩展新增的（`config edit` 现已支持
`key_id` / `algorithm` / `image` / `props` / `prop_from_file`）。

**链式字段的 `--append` 按分区名原地替换**：`chain_partitions` /
`chain_partitions_do_not_use_ab` 的 ITEM **必须是完整的 `PART:SLOT:KEYFILE`
三元组**（SLOT 为数字且 ≥ 1，KEYFILE 非空）；若该分区已有链条目则替换那一条并
**保留它的位置**，不会产生重复，也不会像 `--set` 那样清掉从镜像读回的其它链。
`--remove` 可以只写裸分区名。

**同一字段同时用 `--set`/`--unset` 与 `--append`/`--remove` 会被拒绝**
（`config.invalid_option_combination`，且不写盘）；不同字段混用是允许的。

实例 —— 硬编码链式分区、vbmeta `flags=1`、并把 `vbmeta_system` 换成 2048 位密钥与
对应算法：

```shell
# 1) vbmeta：flags=1，三条链式分区（重名替换语义）
avbpowertool config edit vbmeta --profile my_device --set flags=1 \
  --append chain_partitions=boot:3:mykey_rsa4096.pem.bin \
  --append chain_partitions=recovery:1:mykey_rsa4096.pem.bin \
  --append chain_partitions=vbmeta_system:2:mykey_rsa2048.pem.bin

# 2) vbmeta_system：换 2048 密钥 + SHA256_RSA2048
avbpowertool config edit vbmeta_system --profile my_device \
  --set key_id=mykey_rsa2048 --set algorithm=SHA256_RSA2048

# 3) 复核
avbpowertool config check-chains --profile my_device --json
```

> 链式条目里的 KEYFILE 必须是 `avbtool extract_public_key` 的产物
> （`*.pem.bin`）：avbtool 把第三段当**原始字节**读入，传 `.pem` 会写坏 vbmeta。
> 用 `config check-chains` 可以发现「链条目公钥与实际签名密钥不一致」
> （`chain.key_mismatch`）。详见 [KEY_MANAGEMENT.md](KEY_MANAGEMENT.md)。

`config edit` 的完整参数语义（含 `--set` 的值写法与全部冲突规则）见
[CLI_REFERENCE.md](CLI_REFERENCE.md#config-edit)。

## 无签名（NONE）分区

v3 支持 `SigningAlgorithm.NONE`：分区仍会添加 hash / hashtree footer 或 vbmeta 内容，
但**不**附加 `--algorithm` / `--key`，因此 avbtool 不计算哈希/签名（等价于未签名镜像）。
NONE hash 分区同样需要 `partition_size` 或 `dynamic_partition_size`。

```python
PartitionConfig(
    image="dtbo.img",
    descriptor=DescriptorType.HASH,
    algorithm=SigningAlgorithm.NONE,   # 无签名
    key_id="",                          # NONE 分区无需 key_id
    partition_name="dtbo",
    partition_size=4194304,             # NONE 也需要分区大小
)
```

vbmeta 的 `included_partitions` / `chain_partitions` 可以引用 NONE 分区；链分区密钥通过
`chain_partitions` 三元组中的公钥文件名解析。

## 导入旧版 v1 配置

v1（AVBPowerTool 1.x）导出的配置 zip 可以自动转换为 v3 配置：

- **TUI**：Settings 页 → `[I] Import v1 legacy config`，选择根目录的 v1 zip。
- **CLI**：`avbpowertool config import-legacy <archive> [--name ID] [--no-activate] [--json]`。

转换会：解码 `imageInfo.json`（保留签名相关字段，`Algorithm: NONE` 映射为
`SigningAlgorithm.NONE`）、补全 vbmeta 链分区三元组、复制 `Keys/` 中的 pem/pub.bin 并生成
`manifest.json`。v1 BATCH 归档会被明确拒绝；转换不修改 v1 源文件。

完整设计见 [LEGACY_CONFIG_IMPORT.md](LEGACY_CONFIG_IMPORT.md)。
