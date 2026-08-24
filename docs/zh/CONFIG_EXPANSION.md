# AVBPowerTool2 配置扩充方案

> 基准：`references/avbtool-android-compose` 中 Android Compose APP 的
> 完整命令数据模型（`AvbModels.kt` 的 `AvbCommands.all`），交叉核对
> 本项目 vendored `avbtool.py` 的 argparse 定义与实现。
>
> 范围：`add_hash_footer`、`add_hashtree_footer`、`make_vbmeta_image`、
> `info_image`、`extract_public_key` 五个命令。
>
> 状态：**已实施** — P0–P7 全部落地，见 §4「实施进度」。配置模型已升级到
> v3 schema；`config migrate` 可将 v2 配置就地迁移到 v3。

---

## 1. 背景与问题分析

### 1.1 现状

AVBPowerTool2 的配置模型（`domain/models.py` 的 `PartitionConfig` +
`infrastructure/persistence/profile_codec.py` 的 v2 JSON 编解码）目前只覆盖了
avbtool 五条命令参数的一小部分：

| 现状字段 | 说明 |
|---|---|
| `image` / `partition_name` / `algorithm` / `key_id` | 命令输入与签名身份 |
| `rollback_index` / `rollback_index_location` | 回滚索引 |
| `salt` / `hash_algorithm` / `flags` / `props` | 描述符基础属性 |
| `included_partitions` / `chain_partitions` | vbmeta 专用 |
| `data_block_size` / `hash_block_size` | hashtree 块大小（**与 avbtool 不符**，见下） |
| `set_hashtree_disabled_flag` / `set_verification_disabled_flag` | 标志位快捷开关 |

### 1.2 严重缺失（必须补齐）

1. **`partition_size` / `dynamic_partition_size` 完全缺失**。
   `avbtool add_hash_footer` 在源码中强制要求二者至少提供一个
   （`avbtool.py` L3439：`if not partition_size and not dynamic_partition_size: raise`）。
   当前模型没有该字段，意味着**现有 hash 分区配置生成的命令必然执行失败**。
2. **`block_size` 建模错误**。avbtool `add_hashtree_footer` 只有一个
   `--block_size`（默认 4096），而当前模型拆成 `data_block_size` +
   `hash_block_size`，`command_builder.py` / `signing_plan.py` 会拼出
   `--data_block_size` / `--hash_block_size` —— 这两个 flag 在 avbtool 中**不存在**，
   命令会被 argparse 直接拒绝。
3. **FEC 参数缺失**。`--do_not_generate_fec`、`--fec_num_roots` 均无法配置。
4. **`--output` 非法参数**。当前 `build_hash_footer_command` /
   `_build_hashtree_command` 对 footer 命令传 `--output <staging>`，但
   `add_hash_footer` / `add_hashtree_footer` **没有** `--output` flag
   （它们原地修改镜像文件）。生成的是非法命令。

### 1.3 高频可选缺失（功能缺口）

`--calc_max_image_size`、`--do_not_append_vbmeta_image`、
`--output_vbmeta_image`、`--use_persistent_digest`、`--do_not_use_ab`、
`--no_hashtree`、`--check_at_most_once`、`--setup_as_rootfs_from_kernel`、
`--kernel_cmdline`（当前仅支持单字符串，avbtool 可重复）、
`--chain_partition_do_not_use_ab`、`--padding_size`（vbmeta）等均无法配置。

### 1.4 Android 数据模型的可借鉴点

Android 工程用一个声明式表 `AvbCommands.all`（`AvbArg(key, type, required,
defaultValue, advanced, repeatable, ...)`）**完整描述每条命令的参数**，
GUI 表单、参数校验都从这张表驱动。AVBPowerTool2 目前没有等价物，
配置字段与 avbtool flag 的映射散落在 `signing_plan.py` / `command_builder.py`
两个地方且相互重复、已经出现漂移（如 `--output`、`data_block_size` 的错误）。

---

## 2. 五命令参数完整提取（必选 / 可选）

> 类型列使用 Android 的 `ArgType` 语义；「现状」列：
> ✅ = 已建模且映射正确，⚠️ = 已建模但映射有误，❌ = 缺失。
> 标注「高级」的项对应 Android 模型 `advanced = true`（GUI 折叠在
> Advanced 区块），配置中对应「进阶」分组。

### 2.1 `add_hash_footer`

| # | Android 键 | avbtool flag | 类型 | 必选 | 默认值 | 高级 | 现状 |
|---|---|---|---|---|---|---|---|
| 1 | `--image` | `--image` | 输入文件 | **必选** | — | 否 | ✅ `config.image` |
| 2 | `--partition_size` | `--partition_size` | SIZE | 条件必选 ① | — | 否 | ❌ |
| 3 | `--dynamic_partition_size` | `--dynamic_partition_size` | BOOL | 条件必选 ① | `false` | 否 | ❌ |
| 4 | `--partition_name` | `--partition_name` | TEXT | 可选 | 无 | 否 | ✅ |
| 5 | `--hash_algorithm` | `--hash_algorithm` | HASH_ALGORITHM | 可选 | `sha256` | 否 | ✅ |
| 6 | `--salt` | `--salt` | TEXT | 可选 | 随机生成 | 否 | ✅ |
| 7 | `--algorithm` | `--algorithm` | ALGORITHM | 可选 | `NONE` | 否 | ✅ |
| 8 | `--key` | `--key` | FILE | 可选 | — | 否 | ✅ |
| 9 | `--calc_max_image_size` | `--calc_max_image_size` | BOOL | 可选 | `false` | 否 | ❌ |
| 10 | `--do_not_append_vbmeta_image` | `--do_not_append_vbmeta_image` | BOOL | 可选 | `false` | 否 | ❌ |
| 11 | `--rollback_index` | `--rollback_index` | INT | 可选 | `0` | 否 | ✅ |
| 12 | `--prop` | `--prop` | TEXT（可重复） | 可选 | — | 否 | ✅ `props` |
| 13 | `--include_descriptors_from_image` | 同左 | FILE（可重复） | 可选 | — | 否 | ❌ |
| 14 | `--flags` | `--flags` | FLAGS | 可选 | `0` | 否 | ✅ |
| 15 | `--output_vbmeta_image` | 同左 | TEXT | 可选 | — | **是** | ❌ |
| 16 | `--signing_helper` | 同左 | TEXT | 可选 | — | **是** | ❌ |
| 17 | `--signing_helper_with_files` | 同左 | TEXT | 可选 | — | **是** | ❌ |
| 18 | `--public_key_metadata` | 同左 | FILE | 可选 | — | **是** | ❌ |
| 19 | `--rollback_index_location` | 同左 | INT | 可选 | `0` | **是** | ✅ |
| 20 | `--append_to_release_string` | 同左 | TEXT | 可选 | — | **是** | ❌ |
| 21 | `--prop_from_file` | 同左 | TEXT（可重复） | 可选 | — | **是** | ❌ |
| 22 | `--kernel_cmdline` | 同左 | TEXT（可重复） | 可选 | — | **是** | ⚠️ 单字符串 |
| 23 | `--setup_rootfs_from_kernel` | 同左 | FILE | 可选 | — | **是** | ❌ |
| 24 | `--print_required_libavb_version` | 同左 | BOOL | 可选 | `false` | **是** | ❌ |
| 25 | `--chain_partition` | 同左 | CHAIN_PARTITION（可重复） | 可选 | — | **是** | ❌（仅 vbmeta 有） |
| 26 | `--chain_partition_do_not_use_ab` | 同左 | TEXT（可重复） | 可选 | — | **是** | ❌ |
| 27 | `--set_hashtree_disabled_flag` | 同左 | BOOL | 可选 | `false` | **是** | ✅ |
| 28 | `--set_verification_disabled_flag` | 同左 | BOOL | 可选 | `false` | **是** | ✅ |
| 29 | `--use_persistent_digest` | 同左 | BOOL | 可选 | `false` | **是** | ❌ |
| 30 | `--do_not_use_ab` | 同左 | BOOL | 可选 | `false` | **是** | ❌ |

① `avbtool.py` L3439：`partition_size` 与 `dynamic_partition_size` **至少提供其一**，
否则直接抛错；两者与 `--calc_max_image_size` 同时给出也会报错（L3443）。

### 2.2 `add_hashtree_footer`

| # | Android 键 | avbtool flag | 类型 | 必选 | 默认值 | 高级 | 现状 |
|---|---|---|---|---|---|---|---|
| 1 | `--image` | `--image` | 输入文件 | **必选** | — | 否 | ✅ |
| 2 | `--partition_size` | `--partition_size` | SIZE | 可选 | `0`（追加到末尾） | 否 | ❌ |
| 3 | `--partition_name` | `--partition_name` | TEXT | 可选 | `''` | 否 | ✅ |
| 4 | `--hash_algorithm` | `--hash_algorithm` | HASH_ALGORITHM | 可选 | avbtool 默认 `sha1`（兼容），推荐显式 `sha256` | 否 | ✅（默认 sha256） |
| 5 | `--salt` | `--salt` | TEXT | 可选 | 随机生成 | 否 | ✅ |
| 6 | `--algorithm` | `--algorithm` | ALGORITHM | 可选 | `NONE` | 否 | ✅ |
| 7 | `--key` | `--key` | FILE | 可选 | — | 否 | ✅ |
| 8 | `--block_size` | `--block_size` | INT | 可选 | `4096` | 否 | ⚠️ 见 §1.2-2 |
| 9 | `--do_not_generate_fec` | 同左 | BOOL | 可选 | `false` | 否 | ❌ |
| 10 | `--fec_num_roots` | 同左 | INT | 可选 | `2` | 否 | ❌ |
| 11 | `--calc_max_image_size` | 同左 | BOOL | 可选 | `false` | 否 | ❌ |
| 12 | `--do_not_append_vbmeta_image` | 同左 | BOOL | 可选 | `false` | 否 | ❌ |
| 13 | `--rollback_index` | 同左 | INT | 可选 | `0` | 否 | ✅ |
| 14 | `--prop` | 同左 | TEXT（可重复） | 可选 | — | 否 | ✅ |
| 15 | `--chain_partition` | 同左 | CHAIN_PARTITION（可重复） | 可选 | — | 否 | ❌ |
| 16 | `--flags` | 同左 | FLAGS | 可选 | `0` | 否 | ✅ |
| 17 | `--include_descriptors_from_image` | 同左 | FILE（可重复） | 可选 | — | 否 | ❌ |
| 18 | `--output_vbmeta_image` | 同左 | TEXT | 可选 | — | **是** | ❌ |
| 19 | `--no_hashtree` | 同左 | BOOL | 可选 | `false` | **是** | ❌ |
| 20 | `--check_at_most_once` | 同左 | BOOL | 可选 | `false` | **是** | ❌ |
| 21 | `--setup_as_rootfs_from_kernel` | 同左 | BOOL | 可选 | `false` | **是** | ❌ |
| 22 | `--signing_helper` | 同左 | TEXT | 可选 | — | **是** | ❌ |
| 23 | `--signing_helper_with_files` | 同左 | TEXT | 可选 | — | **是** | ❌ |
| 24 | `--public_key_metadata` | 同左 | FILE | 可选 | — | **是** | ❌ |
| 25 | `--rollback_index_location` | 同左 | INT | 可选 | `0` | **是** | ✅ |
| 26 | `--append_to_release_string` | 同左 | TEXT | 可选 | — | **是** | ❌ |
| 27 | `--prop_from_file` | 同左 | TEXT（可重复） | 可选 | — | **是** | ❌ |
| 28 | `--kernel_cmdline` | 同左 | TEXT（可重复） | 可选 | — | **是** | ⚠️ 单字符串 |
| 29 | `--setup_rootfs_from_kernel` | 同左 | FILE | 可选 | — | **是** | ❌ |
| 30 | `--print_required_libavb_version` | 同左 | BOOL | 可选 | `false` | **是** | ❌ |
| 31 | `--chain_partition_do_not_use_ab` | 同左 | TEXT（可重复） | 可选 | — | **是** | ❌ |
| 32 | `--set_hashtree_disabled_flag` | 同左 | BOOL | 可选 | `false` | **是** | ✅ |
| 33 | `--set_verification_disabled_flag` | 同左 | BOOL | 可选 | `false` | **是** | ✅ |
| 34 | `--use_persistent_digest` | 同左 | BOOL | 可选 | `false` | **是** | ❌ |
| 35 | `--do_not_use_ab` | 同左 | BOOL | 可选 | `false` | **是** | ❌ |

注意：`add_hashtree_footer` **没有** `--dynamic_partition_size`（与
`add_hash_footer` 不同），因此 `dynamic_partition_size` 只对 hash 分区有意义。

### 2.3 `make_vbmeta_image`

| # | Android 键 | avbtool flag | 类型 | 必选 | 默认值 | 高级 | 现状 |
|---|---|---|---|---|---|---|---|
| 1 | `--output` | `--output` | 输出文件 | **必选** | — | 否 | ✅（构建器恒定传入） |
| 2 | `--algorithm` | `--algorithm` | ALGORITHM | 可选 | `NONE` | 否 | ✅ |
| 3 | `--key` | `--key` | FILE | 可选 | — | 否 | ✅ |
| 4 | `--rollback_index` | 同左 | INT | 可选 | `0` | 否 | ✅ |
| 5 | `--rollback_index_location` | 同左 | INT | 可选 | `0` | 否 | ✅ |
| 6 | `--prop` | 同左 | TEXT（可重复） | 可选 | — | 否 | ✅ |
| 7 | `--include_descriptors_from_image` | 同左 | FILE（可重复） | 可选 | — | 否 | ✅（`included_partitions`） |
| 8 | `--chain_partition` | 同左 | CHAIN_PARTITION（可重复） | 可选 | — | 否 | ✅（`chain_partitions`） |
| 9 | `--flags` | 同左 | FLAGS | 可选 | `0` | 否 | ✅ |
| 10 | `--set_hashtree_disabled_flag` | 同左 | BOOL | 可选 | `false` | 否 | ✅ |
| 11 | `--set_verification_disabled_flag` | 同左 | BOOL | 可选 | `false` | 否 | ✅ |
| 12 | `--padding_size` | 同左 | INT | 可选 | `0` | **是** | ❌ |
| 13 | `--signing_helper` | 同左 | TEXT | 可选 | — | **是** | ❌ |
| 14 | `--signing_helper_with_files` | 同左 | TEXT | 可选 | — | **是** | ❌ |
| 15 | `--public_key_metadata` | 同左 | FILE | 可选 | — | **是** | ❌ |
| 16 | `--append_to_release_string` | 同左 | TEXT | 可选 | — | **是** | ❌ |
| 17 | `--prop_from_file` | 同左 | TEXT（可重复） | 可选 | — | **是** | ❌ |
| 18 | `--kernel_cmdline` | 同左 | TEXT（可重复） | 可选 | — | **是** | ⚠️ 单字符串 |
| 19 | `--setup_rootfs_from_kernel` | 同左 | FILE | 可选 | — | **是** | ❌ |
| 20 | `--print_required_libavb_version` | 同左 | BOOL | 可选 | `false` | **是** | ❌ |
| 21 | `--chain_partition_do_not_use_ab` | 同左 | TEXT（可重复） | 可选 | — | **是** | ❌ |

### 2.4 `info_image`

| # | Android 键 | avbtool flag | 类型 | 必选 | 默认值 | 高级 | 现状 |
|---|---|---|---|---|---|---|---|
| 1 | `--image` | `--image` | 输入文件 | **必选** | — | 否 | ✅（`build_inspect_command`） |
| 2 | `--cert` | `--cert` / `--atx` | BOOL | 可选 | `false` | 否 | ❌（inspect 仅传 `--image`） |
| 3 | —（avbtool 额外） | `--output` | 输出文本文件 | 可选 | stdout | 否 | ❌ |
| 4 | —（avbtool 额外） | `--output_pubkey` | 输出公钥文件 | 可选 | — | 否 | ❌ |

Android 模型只暴露 `--cert`；`--output` / `--output_pubkey` 是 avbtool 原生
选项，本项目可按需补上（读取侧，不影响配置 schema 的签名语义）。

### 2.5 `extract_public_key`

| # | Android 键 | avbtool flag | 类型 | 必选 | 默认值 | 高级 | 现状 |
|---|---|---|---|---|---|---|---|
| 1 | `--key` | `--key` | FILE | **必选** | — | 否 | ✅ |
| 2 | `--output` | `--output` | 输出文件 | **必选** | — | 否 | ✅ |

该命令已完整覆盖，无需扩充。

---

## 3. 扩充方案设计

### 3.1 引入命令规格表（移植 Android `AvbCommands.all`）

新增 `avbpowertool/infrastructure/avbtool/command_spec.py`，把 Android 的
声明式模型移植为 Python 版，作为**参数定义的唯一事实来源**：

```python
from enum import Enum
from dataclasses import dataclass, field

class ArgType(Enum):
    IMAGE = "image"          # 输入镜像（工作区路径）
    FILE = "file"            # 其它输入文件（相对 key store / 工作区）
    TEXT = "text"            # 字符串
    INT = "int"              # 整数
    BOOL = "bool"            # 布尔开关
    SIZE = "size"            # 字节数（分区大小）
    ALGORITHM = "algorithm"  # 签名算法枚举
    HASH_ALGORITHM = "hash_algorithm"
    FLAGS = "flags"          # 整数标志位
    CHAIN_PARTITION = "chain_partition"  # PART:SLOT:KEY_PATH

@dataclass(frozen=True)
class CommandArg:
    flag: str                 # avbtool 选项名（含 --）
    config_field: str         # PartitionConfig 字段名
    arg_type: ArgType
    required: bool = False
    default: object | None = None
    advanced: bool = False
    repeatable: bool = False
    applies_to: frozenset[str] = frozenset()  # 适用的描述符类型

@dataclass(frozen=True)
class CommandSpec:
    id: str
    inputs: tuple[CommandArg, ...]
    outputs: tuple[CommandArg, ...]
    args: tuple[CommandArg, ...]
```

规格表内容直接由 §2 的表格转录（示例）：

```python
COMMANDS: dict[str, CommandSpec] = {
    "add_hash_footer": CommandSpec(
        id="add_hash_footer",
        inputs=(CommandArg("--image", "image", ArgType.IMAGE, required=True),),
        args=(
            CommandArg("--partition_size", "partition_size", ArgType.SIZE,
                       applies_to=frozenset({"hash", "hashtree"})),
            CommandArg("--dynamic_partition_size", "dynamic_partition_size", ArgType.BOOL),
            CommandArg("--partition_name", "partition_name", ArgType.TEXT),
            CommandArg("--hash_algorithm", "hash_algorithm", ArgType.HASH_ALGORITHM,
                       default="sha256"),
            CommandArg("--salt", "salt", ArgType.TEXT),
            CommandArg("--algorithm", "algorithm", ArgType.ALGORITHM, default="NONE"),
            CommandArg("--key", "key_id", ArgType.FILE),
            CommandArg("--calc_max_image_size", "calc_max_image_size", ArgType.BOOL),
            CommandArg("--do_not_append_vbmeta_image", "do_not_append_vbmeta_image", ArgType.BOOL),
            CommandArg("--rollback_index", "rollback_index", ArgType.INT, default=0),
            CommandArg("--prop", "props", ArgType.TEXT, repeatable=True),
            CommandArg("--include_descriptors_from_image",
                       "include_descriptors_from_image", ArgType.FILE, repeatable=True),
            CommandArg("--flags", "flags", ArgType.FLAGS, default=0),
            # …… 其余见 §2.1
        ),
    ),
    # "add_hashtree_footer" / "make_vbmeta_image" / "info_image" /
    # "extract_public_key" 同理
}
```

收益：
- 校验、CLI/TUI 表单、命令构建器三处共享同一张表，杜绝字段漂移；
- 新增参数只需改表 + 模型字段，无需改三处代码；
- 与 Android 工程保持一一对应，便于后续移植更多命令
  （`erase_footer`、`resize_image`、`verify_image`、`append_vbmeta_image` 等）。

### 3.2 领域模型：`PartitionConfig` v3

在 `domain/models.py` 中扩展 `PartitionConfig`（保持 frozen dataclass）：

```python
@dataclass(frozen=True)
class PartitionConfig:
    # —— 身份与输入（保持必填）——
    image: str
    descriptor: DescriptorType
    partition_name: str
    algorithm: SigningAlgorithm
    key_id: str

    # —— 分区尺寸（本次新增，hash 必填项）——
    partition_size: int = 0                 # 分区字节数；hash 必需，hashtree 0=追加到末尾
    dynamic_partition_size: bool = False    # 由镜像大小推算（仅 add_hash_footer）

    # —— 回滚 / 摘要（已有字段保留）——
    rollback_index: int = 0
    rollback_index_location: int = 0
    salt: str = ""
    hash_algorithm: str = "sha256"

    # —— 描述符属性 ——
    props: tuple[tuple[str, str], ...] = ()
    prop_from_file: tuple[tuple[str, str], ...] = ()   # (KEY, PATH) 对，新字段
    flags: int = 0
    set_hashtree_disabled_flag: bool = False
    set_verification_disabled_flag: bool = False

    # —— hashtree 专用（修正 + 新增）——
    block_size: int = 4096                  # 替代 data_block_size/hash_block_size
    do_not_generate_fec: bool = False
    fec_num_roots: int = 2
    no_hashtree: bool = False
    check_at_most_once: bool = False
    setup_as_rootfs_from_kernel: bool = False

    # —— vbmeta / footer 通用 ——
    included_partitions: tuple[str, ...] = ()
    include_descriptors_from_image: tuple[str, ...] = ()  # 额外镜像文件（新字段）
    chain_partitions: tuple[str, ...] = ()
    chain_partitions_do_not_use_ab: tuple[str, ...] = ()  # 新字段
    kernel_cmdlines: tuple[str, ...] = ()                 # 替代 kernel_cmdline: str
    setup_rootfs_from_kernel: str = ""                    # 镜像文件路径（新字段）
    padding_size: int = 0                 # make_vbmeta_image --padding_size（新字段）
    output_vbmeta_image: str = ""         # 同时写出 vbmeta 结构到文件（新字段）

    # —— 行为开关（新字段）——
    calc_max_image_size: bool = False
    do_not_append_vbmeta_image: bool = False
    print_required_libavb_version: bool = False
    use_persistent_digest: bool = False
    do_not_use_ab: bool = False

    # —— 签名辅助（新字段，多为 profile 级复用）——
    signing_helper: str = ""
    signing_helper_with_files: str = ""
    public_key_metadata: str = ""
    append_to_release_string: str = ""
```

要点：
- `data_block_size` / `hash_block_size` **删除**，由单一 `block_size` 取代
  （对齐 avbtool 的 `--block_size`）。
- `kernel_cmdline: str` → `kernel_cmdlines: tuple[str, ...]`（avbtool 可重复传入）。
- 所有新字段有默认值 → v2 配置不填也能 decode（向后可读），但**生成的命令
  在缺 `partition_size` 时会被校验拦截**（见 §3.5），提示用户补填。

### 3.3 配置 JSON schema v3

`profile_codec.py`：`SCHEMA_VERSION = 3`。

- encode：只写非默认值（沿用现有"稀疏"风格），`block_size` 只在
  `descriptor == "hashtree"` 时写出。
- decode：缺省字段回填默认值；遇到 v2 文件时先迁移（§3.6）再解析。

完整示例（v3）：

```json
{
  "schema_version": 3,
  "profile": { "id": "my_device", "name": "My Device ROM" },
  "key_store_path": "keys",
  "partitions": {
    "boot": {
      "image": "boot.img",
      "descriptor": "hash",
      "algorithm": "SHA256_RSA4096",
      "key_id": "release_rsa4096",
      "partition_name": "boot",
      "partition_size": 67108864,
      "rollback_index": 1,
      "hash_algorithm": "sha256",
      "salt": "a1b2c3d4e5f6",
      "flags": 0,
      "props": [["com.android.build.fingerprint", "myrom/1.0"]]
    },
    "system": {
      "image": "system.img",
      "descriptor": "hashtree",
      "algorithm": "SHA256_RSA4096",
      "key_id": "release_rsa4096",
      "partition_name": "system",
      "partition_size": 2147483648,
      "block_size": 4096,
      "fec_num_roots": 2,
      "do_not_generate_fec": false,
      "kernel_cmdlines": [
        "androidboot.avb.avb_version=1.2"
      ]
    },
    "vbmeta": {
      "image": "vbmeta.img",
      "descriptor": "vbmeta",
      "algorithm": "SHA256_RSA4096",
      "key_id": "release_rsa4096",
      "partition_name": "vbmeta",
      "rollback_index": 0,
      "padding_size": 0,
      "included_partitions": ["boot", "system"],
      "chain_partitions": ["vbmeta_system:1:system_pub.bin"]
    }
  }
}
```

### 3.4 命令构建器修正与字段 → flag 映射矩阵

#### 3.4.1 必改 Bug

| Bug | 位置 | 修正 |
|---|---|---|
| footer 命令传 `--output` | `command_builder.py` `build_hash_footer_command` / `build_hashtree_footer_command`；`signing_plan.py` `_build_hash_command` / `_build_hashtree_command` | 删除 `--output`。执行流程改为：**先把原镜像复制到 staging，再对 staging 文件原地执行** `add_hash_footer` / `add_hashtree_footer`（`--image <staging路径>`）。`SigningStep.input_path` = 原图，`output_path` = staging 副本 |
| `--data_block_size` / `--hash_block_size` | 同上两处 | 改为单一 `--block_size <config.block_size>` |

#### 3.4.2 新增 flag 映射（command_builder / signing_plan 共用）

`add_hash_footer`：

```
--partition_size <n>                 # partition_size > 0 时
--dynamic_partition_size             # dynamic_partition_size 时
--calc_max_image_size                # calc_max_image_size 时
--do_not_append_vbmeta_image         # 同上（布尔一律"为真才出现"）
--include_descriptors_from_image <p> # include_descriptors_from_image 每项
--output_vbmeta_image <p>            # 路径解析规则见下
--signing_helper <s> / --signing_helper_with_files <s>
--public_key_metadata <p>
--append_to_release_string <s>
--prop_from_file KEY:PATH            # prop_from_file 每项
--kernel_cmdline <s>                 # kernel_cmdlines 每项
--setup_rootfs_from_kernel <p>
--print_required_libavb_version
--chain_partition PART:SLOT:KEY      # chain_partitions 每项（密钥路径解析沿用 _resolve_chain_key）
--chain_partition_do_not_use_ab PART:SLOT:KEY
--use_persistent_digest
--do_not_use_ab
```

`add_hashtree_footer`：同上（去掉 `--dynamic_partition_size`），另加：

```
--block_size <n>
--do_not_generate_fec
--fec_num_roots <n>
--no_hashtree
--check_at_most_once
--setup_as_rootfs_from_kernel
```

`make_vbmeta_image`：现有基础上新增：

```
--padding_size <n>
--prop_from_file KEY:PATH
--kernel_cmdline <s>                 # kernel_cmdlines 每项
--setup_rootfs_from_kernel <p>
--signing_helper / --signing_helper_with_files
--public_key_metadata <p>
--append_to_release_string <s>
--print_required_libavb_version
--chain_partition_do_not_use_ab PART:SLOT:KEY
```

路径解析规则（新增字段中的路径类参数）：
- `output_vbmeta_image`、`public_key_metadata`、`setup_rootfs_from_kernel`、
  `include_descriptors_from_image`：相对路径先按工作区 `Images/` 解析，
  找不到再按 profile 目录 / key store 解析；`prop_from_file` 的 PATH 段按
  工作区 `Images/` 解析。
- `chain_partitions` / `chain_partitions_do_not_use_ab` 的 KEY_PATH 段沿用
  `signing_plan.py::_resolve_chain_key`（相对 key store）。

`info_image`（inspect 用例扩展，不进 schema）：
- `InspectImagesRequest` 增加 `with_cert: bool = False`；
  `build_inspect_command(image_path, cert=False)` 在 `cert` 时追加 `--cert`。

### 3.5 校验规则新增（`domain/validation.py`）

| 规则 | 错误码 | 适用 |
|---|---|---|
| hash 分区：`partition_size > 0` 或 `dynamic_partition_size`，二者至少其一 | `config.missing_partition_size` | hash |
| `dynamic_partition_size` 与 `calc_max_image_size` 互斥 | `config.invalid_option_combination` | hash |
| `partition_size` 为正且为 4096 的倍数（avbtool 要求为 image block size 的倍数） | `config.invalid_partition_size` | hash / hashtree |
| hashtree：`partition_size` 若 > 0，须 ≥ 哈希树+FEC+页脚最小开销 | `config.invalid_partition_size` | hashtree |
| `block_size` 为正的 2 的幂（沿用现有校验，改名） | `config.invalid_block_size` | hashtree |
| `fec_num_roots` 在 2..255（fec 工具约束） | `config.invalid_fec_num_roots` | hashtree |
| `use_persistent_digest` 为真时须同时 `do_not_use_ab`（avbtool 说明） | `config.invalid_option_combination` | hash / hashtree |
| `chain_partitions` / `chain_partitions_do_not_use_ab` 每项格式 `PART:SLOT:KEY_PATH`（恰好 3 段）且 SLOT ≥ 1 | `config.invalid_chain_partition` | hash / hashtree / vbmeta |
| `props` / `prop_from_file` 每项含 `:` | `config.invalid_prop` | 全部 |
| 同一 rollback slot 不得被多个 chain 分区占用（avbtool 运行时检查，提前到校验期） | `config.duplicate_rollback_slot` | vbmeta / hash / hashtree |

### 3.6 v2 → v3 迁移

新增 `infrastructure/persistence/v2_to_v3.py`（仿照现有 `v1_profile_codec.py`）：

```python
def migrate_v2_to_v3(data: dict[str, Any]) -> tuple[dict[str, Any], list[OperationIssue]]:
    # 1. data_block_size / hash_block_size -> block_size
    #    两者不同时取 data_block_size 并产生警告 issue
    # 2. kernel_cmdline: str -> kernel_cmdlines: [str]（非空时）
    # 3. 其余新字段留默认（partition_size=0 等），由校验提示补填
    # 4. schema_version := 3
```

- `decode_profile` 对 `schema_version == 2` 自动迁移并返回迁移警告；
- 迁移是**只读推导**，写回时机由 `config migrate` 命令显式触发（避免静默改写用户文件）；
- 契约测试覆盖：v2 → v3 字段正确、警告正确、无信息丢失。

### 3.7 UI / CLI / i18n 暴露

1. **TUI 向导**（`presentation/tui/views/create_config.py`）：按描述符类型动态展示字段
   —— hash 必问 `partition_size`（或选择"由镜像计算"）；hashtree 展示
   `block_size`、`fec_num_roots`、`do_not_generate_fec`；vbmeta 展示
   `padding_size`、`chain_partitions_do_not_use_ab`、`kernel_cmdlines`。
   高级项折叠到"进阶配置"（对齐 Android GUI 的 advanced 分组）。
2. **CLI**：新增 `avbpowertool config edit [--profile ID]` 交互编辑
   （或在 `config create` 增加 `--advanced` 透传），字段清单由 §3.1 的
   规格表驱动。
3. **i18n**：`locale/*/avbpowertool.po` 增加向导提示与校验消息键
   （`config.wizard.partition_size`、`config.wizard.block_size` 等）。

### 3.8 测试计划

| 测试文件 | 内容 |
|---|---|
| `tests/unit/test_models.py` | v3 新字段默认值、`kernel_cmdlines` 元组语义、frozen 不变性 |
| `tests/unit/test_validation.py` | §3.5 全部新规则（合法/非法用例） |
| `tests/unit/test_command_builder.py` | **修正现有断言**：footer 命令不再含 `--output`、改用 `--block_size`；新增全部 flag 映射断言 |
| `tests/unit/test_signing_plan.py` | staging 副本 + 原地 footer 流程；hash 缺 `partition_size` 时产生 `config.missing_partition_size` |
| `tests/unit/test_profile_codec.py` | v3 round-trip；v2 → v3 迁移测试 |
| `tests/unit/test_v2_to_v3.py` | 迁移字段映射、双 block_size 冲突警告 |
| `tests/contract/test_profile_v3_schema.py` | v3 JSON 契约（必需键、类型、默认值） |
| `tests/integration/test_sign_images.py` | 用 `FakeAvbTool` 验证含新参数的完整计划与执行 |
| `tests/fixtures/profiles/sample_profile.json` | 升级为 v3 示例并新增 `partition_size` 等字段 |

### 3.9 与 Android 模型的对应关系（可追溯性）

| Android 概念 | AVBPowerTool2 落点 |
|---|---|
| `AvbCommands.all` / `AvbArg` | `command_spec.py::COMMANDS` / `CommandArg` |
| `AvbFileInput` / `AvbFileOutput` | `CommandSpec.inputs` / `outputs`（`image` / `output_vbmeta_image` 等） |
| `ArgType`（10 种） | `ArgType` 枚举原样移植 |
| `advanced` 分组 | 配置分「基础 / 进阶」，向导折叠展示 |
| `repeatable` | 元组字段（`props`、`kernel_cmdlines`、`chain_partitions`…） |
| `required` | 校验规则（§3.5） |

---

## 4. 分阶段实施步骤

| 阶段 | 内容 | 验证 | 状态 |
|---|---|---|---|
| **P0 基础** | `command_spec.py` 移植 5 命令规格表 + 单元测试 | `pytest tests/unit/test_command_spec.py` | ✅ |
| **P1 模型** | `PartitionConfig` v3 字段；删除 `data_block_size`/`hash_block_size`；`kernel_cmdlines` | `test_models.py` 全绿 | ✅ |
| **P2 编解码** | `profile_codec` v3 + `v2_to_v3` 迁移 + 契约测试 | round-trip / 迁移测试全绿 | ✅ |
| **P3 校验** | §3.5 规则接入 `validate_partition` | `test_validation.py` 全绿 | ✅ |
| **P4 命令构建** | 修正 `--output` / `--block_size`；新增全部 flag 映射；staging 原地执行流程 | `test_command_builder.py` / `test_signing_plan.py` 全绿 | ✅ |
| **P5 用例** | `InspectImagesRequest.with_cert`；`config migrate` / `config edit` CLI | 集成测试 | ✅ |
| **P6 UI/i18n** | 向导按描述符展示新字段；高级折叠；.po 新键 | `test_cli_contract.py`、l10n 检查 | ✅ |
| **P7 收尾** | 文档同步（CONFIG_CREATION.md、KEY_MANAGEMENT.md、README）；样例 profile 升级 v3 | 全量 `pytest` + ruff + pyright | ✅ |

每个阶段结束执行 AGENTS.md 质量门禁：
`uv run pytest tests/` → `ruff check` → `ruff format` → `pyright`。

### 4.1 落地说明（实现与方案差异）

- `command_spec` / `command_builder` 按架构约束放在 `domain/`
  （`signing_plan` 属于 domain，不能在 domain 里 import infra）；
  `infrastructure/avbtool/command_builder.py` 保留为 re-export shim。
- footer 命令（`add_hash_footer` / `add_hashtree_footer`）不再传 `--output`，
  改为对 staging 副本**原地修改**：`sign_images` 在执行前把原图复制到 staging 路径。
- `--salt ""` 语义：盐为空时省略 `--salt`（avbtool 生成随机盐），与 Android 语义一致。
- v2 → v3 迁移为**只读推导**；`decode_profile` 在内存中自动迁移，
  `config migrate` 才把 v3 写回磁盘。

---

## 5. 附：字段 ↔ 命令映射矩阵（新增字段速查）

| `PartitionConfig` 字段 | add_hash_footer | add_hashtree_footer | make_vbmeta_image |
|---|---|---|---|
| `partition_size` | ✅ `--partition_size` | ✅ `--partition_size` | — |
| `dynamic_partition_size` | ✅ `--dynamic_partition_size` | —（avbtool 无此选项） | — |
| `block_size` | — | ✅ `--block_size` | — |
| `do_not_generate_fec` / `fec_num_roots` | — | ✅ | — |
| `calc_max_image_size` | ✅ | ✅ | — |
| `do_not_append_vbmeta_image` | ✅ | ✅ | — |
| `output_vbmeta_image` | ✅ | ✅ | — |
| `include_descriptors_from_image` | ✅ | ✅ | ✅（与 `included_partitions` 合并传入） |
| `chain_partitions_do_not_use_ab` | ✅ | ✅ | ✅ |
| `kernel_cmdlines` | ✅ | ✅ | ✅ |
| `setup_rootfs_from_kernel` | ✅ | ✅ | ✅ |
| `setup_as_rootfs_from_kernel` | — | ✅ | — |
| `no_hashtree` / `check_at_most_once` | — | ✅ | — |
| `use_persistent_digest` / `do_not_use_ab` | ✅ | ✅ | — |
| `print_required_libavb_version` | ✅ | ✅ | ✅ |
| `padding_size` | — | — | ✅ |
| `prop_from_file` | ✅ | ✅ | ✅ |
| `signing_helper` / `signing_helper_with_files` | ✅ | ✅ | ✅ |
| `public_key_metadata` | ✅ | ✅ | ✅ |
| `append_to_release_string` | ✅ | ✅ | ✅ |

> `info_image` / `extract_public_key` 不进配置 schema（前者增加 `--cert`
> 读取选项，后者已完整）。
