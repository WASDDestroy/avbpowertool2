# CLI 参考

AVBPowerTool2 命令行的完整参考：命令面、参数语义、退出码与错误码。

> 本页的命令、旗标、默认值和用法均逐条取自 `uv run avbpowertool <cmd> --help` 的
> 实际输出，并与实现行为逐项核对过。命令面变更时请同步更新本页（中英两份）。

## 目录

- [1. 运行环境与通用约定](#1-运行环境与通用约定)
- [2. 退出码](#2-退出码)
- [3. `--profile` 与配置解析规则](#3---profile-与配置解析规则)
- [4. 命令参考](#4-命令参考)
  - [`image inspect` / `image sign`](#image-inspect--image-sign)
  - [`config show` / `config validate`](#config-show--config-validate)
  - [`config list` / `config activate`](#config-list--config-activate)
  - [`config create`](#config-create)
  - [`config edit`](#config-edit)
  - [`config check-chains`](#config-check-chains)
  - [`config rename`](#config-rename)
  - [`config delete`](#config-delete)
  - [`config import` / `config import-legacy` / `config export` / `config migrate`](#config-import--config-import-legacy--config-export--config-migrate)
  - [`keys list` / `keys discover` / `keys ensure-public` / `keys add` / `keys remove`](#keys-子命令)
  - [`plugin` 子命令](#plugin-子命令)
  - [`about`](#about)
- [5. 错误码清单](#5-错误码清单)
- [6. 端到端示例](#6-端到端示例)

---

## 1. 运行环境与通用约定

CLI 与 TUI 共用同一个入口：带参数走 CLI，不带参数启动 TUI。

```shell
avbpowertool image inspect boot vbmeta   # 带参数 -> CLI
avbpowertool                             # 不带参数 -> TUI
```

- **工作区根目录 = 当前工作目录**。`avbtool.py`、`Images/`、`profiles/`、`Logs/`、
  `.active-profile`、`.avbpowertool-staging/` 全部相对它解析。本页所有示例都假定
  你在仓库根目录执行。
- 未安装控制台脚本（或它不在 `PATH` 上）时，用 `python -m avbpowertool ...`
  代替，行为完全一致。
- **`--json`**：除 `about` 外所有子命令都支持。输出可被 PowerShell
  `ConvertFrom-Json` 直接消费；失败时错误同样以 JSON 表达
  （`issues[].error_code` + `issues[].message`），并配合非 0 退出码。
- **镜像名解析**：`image inspect` / `image sign` 的位置参数是**逻辑镜像名**，
  在工作区 `Images/` 下解析为 `<name>.img`。`config create --images` 同时接受
  `boot` 与 `boot.img`（`.img` 后缀会被去掉，重复项只保留第一次出现的位置）。
- **只读与写盘**：`config show` / `config validate` / `config check-chains` /
  `image inspect` / `keys list` / 所有 `--help` 都是只读的，不会改写任何文件。
  `config edit` / `config create` / `config rename` / `config delete` /
  `keys ...` 会写盘。注意：**任何 `save` 都会用 `encode_profile` 重排并省略默认值地重写整个
  `profile.json`**，手工排版会丢失。
- **已弃用别名**：`read` / `sign` / `get_all_config` / `check_l10n` 仍然接受，
  但会打印弃用警告后转发到新命令，行为不再单独保证。

---

## 2. 退出码

| 退出码 | 触发条件 |
|---|---|
| `0` | 成功。也用于「错误码前缀不在下表任何一类」的 issue —— 未知前缀不会把成功变成失败。**`plugin run` 的特例**：插件成功启动（`issues` 为空）时返回**插件自己的退出码**，即使它是非 0 |
| `1` | issue 中出现 `config.*` / `keys.*` / `image.*` / `chain.*` / `plugin.*` 前缀；另外三种显式情况：`config validate` 报告了 `missing_images` / `missing_keys`；`image sign --execute` / `config delete` / `plugin uninstall` 没有同时给 `--yes`（stderr 分别打印 `This will modify image files. Use --yes to confirm.`、`This deletes the profile directory including its private keys. Use --yes to confirm.` 与 `This deletes the plugin directory including any bundled files. Use --yes to confirm.`） |
| `2` | argparse 用法错误：未知命令或旗标、缺少必填参数、互斥旗标同时给出（`--from-images` + `--allow-empty`、`--activate` + `--no-activate`、`--merge` + `--replace`），以及 `config create --overwrite` 没给 `--from-images` |
| `3` | issue 中出现 `tool.*` / `signing.*` 前缀（avbtool 子进程失败、签名步骤失败） |

映射实现见 `avbpowertool/presentation/cli/renderer.py::exit_code_from_issues`：
只要有**任意一个** issue 的前缀属于高优先级类别，就返回该类别的退出码
（`tool` / `signing` 优先于 `config` / `keys` / `chain` / `image` / `plugin`）。

**`plugin run` 是唯一的例外**：它有 issue（插件根本没启动，此时 `exit_code` 是占位的
`-1`）时按上表返回 `1`；没有 issue 时**原样返回插件自己的退出码**——包括插件主动退出
的非 0 状态。因此脚本判断 `plugin run` 失败要看 `issues[]` 是否为空，不能只看退出码：

```powershell
$data = avbpowertool plugin run testkey_config_gen --json | ConvertFrom-Json
if ($data.issues.Count -gt 0) { throw "plugin never started" }
if ($data.exit_code -ne 0) { throw "the plugin itself failed" }
```

脚本里的典型用法：

```powershell
avbpowertool config check-chains --profile my_config --json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw "chain check failed" }
```

---

## 3. `--profile` 与配置解析规则

`config show` / `config validate` / `config check-chains` / `image sign` 接受
`--profile PROFILE`，默认值为 `current`。解析规则**字面优先**，顺序固定：

```
1. PROFILE 非空，且 profiles/<PROFILE>/profile.json 存在   -> 用 PROFILE 本身
2. PROFILE 为 "current"（或空），且 .active-profile 指向一个存在的配置
                                                          -> 用该活动配置的 id
3. 否则 -> ConfigError：
     - 请求是 current/空 但没有活动配置 -> config.no_active_profile
     - 其它情况                        -> config.not_found
```

要点：

- **字面优先**意味着一个真的叫 `current` 的配置永远可用
  （`profiles/current/profile.json` 存在时，`--profile current` 就用它，
  不会去看 `.active-profile`）。这是为向后兼容保留的行为。
- `.active-profile` 里写的是 profile id；指向不存在的目录时视同「没有活动配置」。
- 「存在」的判定标准是 `profiles/<id>/profile.json` 存在 —— 只有目录、
  没有 `profile.json` 的不算配置。
- **没有活动配置时的报错**（已实测）：

  ```shell
  $ avbpowertool config show --json
  {
    "config_name": "current",
    "partitions": [],
    "issues": [
      {
        "error_code": "config.no_active_profile",
        "message": "No active profile; use 'config activate' or pass an explicit --profile"
      }
    ]
  }
  # exit 1
  ```

- **key store 相关用例是宽容解析**：`keys list` / `keys discover` /
  `keys ensure-public` / `keys add` / `keys remove` 先做同样的「字面优先 +
  current→活动配置」解析，但**非空请求解析失败时按字面值继续**，由用例自己报
  `keys.directory_not_found`。这样创建向导可以先建好
  `profiles/<id>/keys/`、稍后才写 `profile.json`。只有「请求为空且没有活动配置」
  才直接报 `config.no_active_profile`。
- `config edit` / `config migrate` 的 `--profile` 默认值也是 `current`，同样走
  上面的严格解析（无活动配置时 `config.no_active_profile`）。它们的 `--help`
  文案只写了 `(default: current)`，行为与上表一致。
- `config export` / `config rename` / `config delete` / `config import-legacy`
  **不接受** `--profile`：它们用位置参数显式指定 id（脚本始终知道 id）。

---

## 4. 命令参考

### `image inspect` / `image sign`

```
avbpowertool image inspect [-h] [--cert] [--json] images [images ...]
avbpowertool image sign    [-h] [--dry-run] [--execute] [--yes] [--profile PROFILE]
                              [--remove-footers] [--json] images [images ...]
```

`image inspect`（只读，**唯一不依赖配置的命令**）

| 参数 | 说明 |
|---|---|
| `images`（1 个以上，必填） | 逻辑镜像名，解析为 `Images/<name>.img` |
| `--cert` | 额外读取证书（传给 avbtool `--cert`） |
| `--json` | JSON 输出 |

`--json` 顶层键：`images[]`、`issues[]`。每个 `images[]` 含
`image_name` / `image_path` / `descriptor` / `algorithm` / `partition_name` /
`public_key_sha1` / `rollback_index` / `salt` / `digest` / `flags` / `props[]` /
`included_partitions[]` / `chain_partitions[]`（含 `partition_name`、
`rollback_index_location`、`public_key_sha1`）/ `extensions[]`。
`descriptor` 为 `null` 表示镜像没有 AVB 结构（`image.no_vbmeta_structure`）。

`image sign`

| 参数 | 说明 |
|---|---|
| `images`（1 个以上，必填） | 逻辑镜像名 |
| `--dry-run` | 只生成签名计划、不执行。**默认即为真**（`store_true` + `default=True`），显式写上只是为了可读性 |
| `--execute` | 真正执行签名（需要 `--yes`）。给出后 `--dry-run` 被覆盖为假 |
| `--yes` | 确认执行。缺少时 `--execute` 只打印提示并以退出码 1 结束，**不改动任何文件** |
| `--profile PROFILE` | 配置 id，默认 `current`（按第 3 节解析为活动配置） |
| `--remove-footers` | 执行前先移除已有 footer |
| `--json` | JSON 输出 |

`--json` 顶层键：`executed` / `success_count` / `fail_count` / `plan`
（含 `profile_id` / `steps[]` / `vbmeta_order[]`）/ `issues[]`。
注意 `plan.steps[]` 是**计划**，`--dry-run` 下 `executed` 为 `false`。

### `config show` / `config validate`

```
avbpowertool config show     [-h] [--profile PROFILE] [--json]
avbpowertool config validate [-h] [--profile PROFILE] [--json]
```

两者都**只读**。

- `config show --json` 顶层键：`config_name`、`partitions[]`、`issues[]`。
  每个分区含 `image_name` / `image` / `descriptor` / `algorithm` / `key_id` /
  `partition_name` / `rollback_index` / `partition_size` /
  `dynamic_partition_size` / `rollback_index_location` / `salt` /
  `hash_algorithm` / `flags` / `props[]`（`[key, value]` 二元组数组）/
  `included_partitions[]` / `include_descriptors_from_image[]` /
  `chain_partitions[]` / `chain_partitions_do_not_use_ab[]`。
- `config validate --json` 顶层键：`config_name`、`missing_images[]`、
  `missing_keys[]`、`issues[]`。**`missing_images` / `missing_keys` 非空也会让
  退出码为 1**（它们以数据而非 issue 的形式返回），所以脚本只需判断退出码。

### `config list` / `config activate`

```
avbpowertool config list     [-h] [--json]
avbpowertool config activate [-h] [--json] profile
```

- `config list --json`：`profiles[]`（`profile_id` / `name` / `is_active` /
  `partition_count`）、`active_profile_id`（无活动配置时为 `null`）、`issues[]`。
- `config activate <profile>` 把 `<profile>` 写入 `.active-profile`。
  不存在的 id → `config.not_found`；写盘失败 → `config.activate_failed`。
  删除活动配置会被拒绝（`config.active_delete_forbidden`）。

### `config create`

```
avbpowertool config create [-h] --id PROFILE_ID [--name PROFILE_NAME]
                           [--from-images [DIR] | --allow-empty]
                           [--images NAMES] [--key KEY_ID]
                           [--no-chain-resolve] [--include-fallback]
                           [--skip-non-avb] [--overwrite]
                           [--activate | --no-activate] [--json]
```

| 参数 | 说明 |
|---|---|
| `--id PROFILE_ID`（必填） | 新配置 id，同时是目录名。必须只含字母、数字、`_`、`-`、`.`，否则 `config.invalid_profile_id`（**不会**被静默改名） |
| `--name PROFILE_NAME` | 显示名，默认取 `--id` 的值 |
| `--from-images [DIR]` | 从镜像生成分区。**不带值 = 工作区 `Images/`**；带值 = 该目录 |
| `--allow-empty` | 允许零分区创建（`config.no_partitions` 被过滤掉） |
| `--images NAMES` | 逗号分隔的镜像名（`boot,dtbo` 或 `boot.img`），可重复；仅与 `--from-images` 配合 |
| `--key KEY_ID` | 给所有生成的分区指定同一个 key_id，默认自动选择 |
| `--no-chain-resolve` | 不解析从 vbmeta 读回的链式分区（默认**会**解析） |
| `--include-fallback` | 内嵌描述符被剪空时回退为「其它所有被扫描分区」（默认关闭，见下） |
| `--skip-non-avb` | 跳过没有 AVB 结构的镜像，而不是失败 |
| `--overwrite` | 复用已存在的配置目录（保留其 `keys/`，替换分区集合）；需要 `--from-images`，否则退出码 2 |
| `--activate` / `--no-activate` | 是否写 `.active-profile`。**默认不激活**（`--no-activate` 是默认值） |
| `--json` | JSON 输出 |

**`--allow-empty` 与 `--from-images` 互斥**：argparse 层直接拒绝，退出码 2：

```
avbpowertool config create: error: argument --from-images: not allowed with argument --allow-empty
```

（注意：计划文档曾写这一冲突映射为 `config.invalid_option_combination`；
实际实现是 argparse 的互斥组，退出码 2，不产生 issue。）

`--allow-empty` 路径（`ConfigCreateUseCase`）

- 落盘 `profiles/<id>/profile.json`（`partitions` 为空）、`profiles/<id>/keys/`，
  并且**仅在 `keys/manifest.json` 尚不存在时**写入 `{}`（不覆盖已发现的密钥）。
- 同 id 已存在 → `config.profile_exists`。
- `--overwrite` **需要 `--from-images`**：在本路径上（以及既没给
  `--from-images` 也没给 `--allow-empty` 的路径上）会被拒绝，向 stderr 打印
  `error: --overwrite requires --from-images`，退出码 2，且不写盘。
- `--json` 顶层键：`profile_id`、`created`、`issues[]`。

`--from-images` 路径（`ConfigCreateFromImagesUseCase`）—— 执行顺序固定，
每个提前返回都**不写盘**：

1. id 必须原样合法，否则 `config.invalid_profile_id`；
2. `profiles/<id>/` 已存在且没给 `--overwrite` → `config.profile_exists`；
3. `--images` 里**显式请求的镜像必须存在**，否则 `image.not_found`
   （并且不创建配置）。`--images` 为空则扫描目录内全部 `*.img`（按名排序）；
4. 逐张 `info_image` 检查；
5. **无 AVB 结构的镜像默认致命**：产生 `image.no_vbmeta_structure` 并失败退出；
   给出 `--skip-non-avb` 才跳过，并记入 `skipped_images`；
6. 一个分区都生成不出来 → `config.no_partitions`（想建空配置请用 `--allow-empty`）；
7. 写盘（`--overwrite` 保留已有 `keys/`）；链解析失败**不阻断创建**，
   链式公钥在密钥库中找不到时记入 `chain_issues`（信息性），**不影响退出码**：
   `created` 仍为 `true`、退出码仍为 0，提示照常完整打印；
8. 生成后跑一次 `config validate`，把 `missing_keys` 并入结果（**仅供参考，
   缺失密钥不会让创建失败**）。

`--include-fallback` 的语义：vbmeta 的内嵌描述符在扫描集合里全部被剪空时，
CLI **默认保留剪空后的结果**（可能为空）；若该 vbmeta 既无
`included_partitions` 也无 `chain_partitions`，会报
`config.vbmeta_no_contents`（退出码 1，但配置**仍会被创建**）。加上
`--include-fallback` 才恢复 TUI 向导的历史行为 —— 回退为「其它所有被扫描的
非 vbmeta 分区」。（计划文档提到的「改为报 `config.vbmeta_no_contents`」在
实现里就是上面这条校验 issue，不是单独的失败分支。）

`--json` 顶层键：`profile_id`、`created`、`partition_count`、`chain_count`、
`scanned_images[]`、`skipped_images[]`、`missing_keys[]`、`issues[]`、
`chain_issues[]`（与 `issues[]` 同构的 `{error_code, message}` 数组；链解析
失败只出现在这里，**不进入 `issues[]`**，因此不影响退出码）。

### `config edit`

```
avbpowertool config edit [-h] [--profile PROFILE] [--set FIELD=VALUE]
                         [--unset FIELD] [--append FIELD=ITEM]
                         [--remove FIELD=ITEM] [--json] partition
```

只编辑**一个分区**的字段；`partition` 是位置参数（分区名，如 `boot`）。

| 参数 | 说明 |
|---|---|
| `--profile PROFILE` | 配置 id，默认 `current` |
| `--set FIELD=VALUE` | 设置字段，**整字段替换**。可重复。布尔写 `true`/`false`（也接受 `1`/`yes`/`on`） |
| `--unset FIELD` | 把字段重置为空值：`str -> ''`、`int -> 0`、`bool -> false`、`tuple -> ()`。可重复 |
| `--append FIELD=ITEM` | 向**元组字段**追加一项。可重复 |
| `--remove FIELD=ITEM` | 从**元组字段**删除匹配项。可重复 |
| `--json` | JSON 输出 |

**可编辑字段白名单**（白名单是唯一入口，其它字段一律 `config.invalid_field`）：

| 类别 | 字段 |
|---|---|
| 整数 | `partition_size`、`rollback_index`、`rollback_index_location`、`flags`、`block_size`、`fec_num_roots`、`padding_size` |
| 布尔 | `dynamic_partition_size`、`do_not_generate_fec`、`calc_max_image_size`、`do_not_append_vbmeta_image`、`no_hashtree`、`check_at_most_once`、`setup_as_rootfs_from_kernel`、`use_persistent_digest`、`do_not_use_ab`、`set_hashtree_disabled_flag`、`set_verification_disabled_flag`、`print_required_libavb_version` |
| 字符串 | `salt`、`hash_algorithm`、`output_vbmeta_image`、`setup_rootfs_from_kernel`、`signing_helper`、`signing_helper_with_files`、`public_key_metadata`、`append_to_release_string`、**`key_id`** |
| 算法枚举 | **`algorithm`**（经 `SigningAlgorithm.from_str`，非法值 → `config.invalid_algorithm`） |
| 镜像文件 | **`image`**（必须以 `.img` 结尾，否则 `config.invalid_field`） |
| 元组 | `kernel_cmdlines`、`chain_partitions`、`chain_partitions_do_not_use_ab`、`included_partitions`、`include_descriptors_from_image`、**`props`**、**`prop_from_file`** |

（加粗项是本轮 CLI 扩展新增的：`key_id` / `algorithm` / `image` / `props` /
`prop_from_file`。）

值的写法：

- 元组字段用**逗号分隔**：`--set kernel_cmdlines=a,b`、
  `--set included_partitions=boot,system`。`--set` 会替换整个元组。
- `props` / `prop_from_file` 是 `KEY:VALUE` / `KEY:PATH` 二元组，
  同样逗号分隔：`--set props=key1:val1,key2:val2`。值里可以含 `:`（只按第一个
  `:` 切分）；键为空或缺少 `:` → `config.invalid_field`。
- `--append props=key:value` 一次只接受**一个** `KEY:VALUE` 对。
- `key_id` 允许设为空串（NONE 分区）：`--set key_id=` 合法。
- `--unset image` / `--unset algorithm` 会被拒绝（它们不接受空值），分别报
  `config.invalid_field` / `config.invalid_algorithm`；`--unset key_id`、
  `--unset props` 正常。

**`--append` / `--remove` 的元组语义**

- 普通元组字段：追加一项 / 删除完全匹配项。
- `chain_partitions` / `chain_partitions_do_not_use_ab`（链式字段）：
  - `--append` 的 ITEM **必须是完整的三元组 `PART:SLOT:KEYFILE`**，
    `SLOT` 为纯数字且 `>= 1`，`KEYFILE` 非空；只写 `boot:3` 会被拒绝并报
    `config.invalid_field`。KEYFILE 里可以再含 `:`（只按前两个 `:` 切分，
    方便写 Windows 路径）。
  - `--append` **按分区名原地替换**：若该分区已存在链条目，则替换那一条并
    **保留它的位置**，不会产生重复项，也不会像 `--set` 那样清掉从镜像读回的
    其它链。这正是「硬编码链式数据 + 重名替换」所需的语义。
  - `--remove` **按分区名匹配**，裸分区名（`--remove chain_partitions=vbmeta_vendor`）
    或完整三元组都行。
- 执行顺序：先全部 `--remove`，再全部 `--append`；同一次调用里的顺序稳定。

**冲突拒绝**：同一个字段不能同时用「整字段形式」（`--set` / `--unset`）和
「逐项形式」（`--append` / `--remove`），否则报
`config.invalid_option_combination`，**不改动磁盘**：

```
[config.invalid_option_combination] Field(s) chain_partitions given in both
--set/--unset and --append/--remove; use one form per field
[config.invalid_option_combination] Field(s) flags given in both --set and --unset;
use one form per field
```

冲突是**按字段**判定的：`--set flags=1 --append chain_partitions=...` 是两个
不同字段，允许。

**其它失败**：分区不在配置里 → `config.partition_missing`；目录名与
`profile.json` 里的 `profile.id` 不一致 → `config.profile_id_mismatch`
（拒绝写入，避免写到另一个配置）；写盘失败 → `config.save_failed`。
**任一 issue 出现时都不会写盘**（先解析、校验，最后才 `save`）。

`--json` 顶层键：`profile_id`、`partition_name`、`issues[]`。

### `config check-chains`

```
avbpowertool config check-chains [-h] [--profile PROFILE] [--json]
```

**只读**校验（唯一可能创建的文件是
`.avbpowertool-staging/check-chains/` 下的临时公钥），遍历配置里
**每个分区的每条 `chain_partitions` 条目**，一次报出全部问题而不是遇到第一个就停。
检查项：

1. 条目格式：`PART:SLOT:KEYFILE`，`SLOT` 为数字且 `>= 1` —— 否则
   `chain.malformed_entry`；
2. `PART` 是否在配置中 —— 否则 `config.missing_included_partition`
   （此时无法继续比较，直接返回）；
3. 被链分区是否是**未签名**（`algorithm = NONE`）—— 是则
   `chain.chained_partition_unsigned`（链校验无意义，直接返回）；
4. `KEYFILE` 是否存在于 key store（相对路径按 `profiles/<id>/keys/` 解析）
   —— 否则 `chain.key_file_missing`；
5. 被链分区 `key_id` 是否在 manifest 中 —— 否则 `config.key_missing`；
   公钥文件读不出来 / 提取失败 → `keys.public_key_extract_failed`；
6. **`KEYFILE` 的 SHA1 是否等于被链分区实际签名密钥的公钥 SHA1** ——
   不等则 `chain.key_mismatch`（这是发现「链条目公钥与实际签名密钥不一致」的
   关键检查，也是本仓库真实配置当前的失败点）。

公钥来源：优先用 manifest 里缓存的 `public_key` 文件；没有就用
`avbtool extract_public_key` 提取到 staging 目录（**不写进 key store**）。

`--json` 顶层键：`profile_id`、`checked`（检查的条目数）、`issues[]`、
`entries[]`（每条 `partition_name` / `entry` / `ok`）。文本模式形如：

```
Profile: e2e
  FAIL [vbmeta] vbmeta_system:2:testkey_rsa2048.pem.bin
Checked 1 chain entr(ies): 0 OK, 1 failed.
  [chain.key_mismatch] Partition 'vbmeta': chain entry '...' uses '...' (sha1 ...), but '...' is signed with key id '...' (public key '...', sha1 ...)
```

### `config rename`

```
avbpowertool config rename [-h] [--name NEW_NAME] [--json] OLD NEW
```

| 参数 | 说明 |
|---|---|
| `OLD`（必填） | 当前配置 id（目录名） |
| `NEW`（必填） | 新配置 id（目录名）。**与 `OLD` 相同时只改显示名** |
| `--name NEW_NAME` | 新的显示名，默认保持不变 |
| `--json` | JSON 输出 |

执行顺序（每步失败都在写任何东西之前返回）：

1. `NEW` 必须原样通过 id 校验 → 否则 `config.invalid_profile_id`；
2. `profiles/<OLD>/profile.json` 必须存在（只有目录不算）→ 否则 `config.not_found`；
3. `profiles/<NEW>` 不能已存在（除非就是旧配置自己）→ 否则 `config.profile_exists`；
4. 目录改名；`OSError`（例如 Windows 上目录被占用）会先尽力回滚，再报
   `config.rename_failed`，不会留下改了一半的配置；
5. 重写 `profile.json` 的 `profile.id = NEW`（给了 `--name` 则同时改
   `profile.name`），保证「目录名 == profile.id」不变式；
6. `.active-profile` 原本指向 `OLD` 时跟随改成 `NEW`。

`OLD == NEW` 时不移动目录（`renamed` 为 `false`），只写显示名 —— 以及在
`profile.json` 内嵌 id 与目录名不一致时顺便修正 id。

`--json` 顶层键：`old_profile_id`、`profile_id`、`renamed`、`name_changed`、`issues[]`。

### `config delete`

```
avbpowertool config delete [-h] [--yes] [--force] [--json] profile
```

**破坏性命令**：删除 `profiles/<profile>/` **整个目录**，包括 `keys/` 下的私钥。
没有回收站、没有软删除、没有「按前缀/时间戳批量清理」——一次只删一个显式 id。

| 参数 | 说明 |
|---|---|
| `profile`（必填） | 要删除的配置 id（目录名） |
| `--yes` | **硬门槛**：不给时什么都不删，stderr 打印 `This deletes the profile directory including its private keys. Use --yes to confirm.` 并返回退出码 `1` |
| `--force` | 允许删除**活动配置**；删除后会清掉指向它的 `.active-profile` |
| `--json` | JSON 输出 |

判定顺序（每步失败都在删除任何东西之前返回）：

1. **`--yes` 门槛**：缺 `--yes` → stderr 提示 + 退出码 `1`，连用例都不会构造；
2. **id 安全校验**：id 为空、为 `.` / `..`、或含路径分隔符（`/`、`\`）
   → `config.invalid_profile_id`；随后再确认
   `profiles/<id>` 解析后**正好是 `profiles/` 的直接子目录**，否则同样报
   `config.invalid_profile_id`（防止 `rmtree` 越界到工作区甚至更上层）；
3. `profiles/<profile>/profile.json` 必须存在（只有目录不算）→ 否则 `config.not_found`；
4. 目标是**活动配置**且未给 `--force` → `config.active_delete_forbidden`，目录保持原样；
5. **统计**目录下的普通文件数与字节数（在 `rmtree` **之前**统计，所以 `deleted_files` /
   `deleted_bytes` 描述的是「删掉了什么」）；
6. 删除目录；`OSError`（例如 Windows 上文件被占用）→ `config.delete_failed`，
   此时 `deleted` 为 `false`；
7. 第 4 步用了 `--force` 且 `.active-profile` 内容**正好**是被删 id 时，unlink 该文件
   （文件不存在则忽略）；指向**别的**配置时不动它。

`--json` 顶层键：`profile_id`、`deleted`、`deleted_files`、`deleted_bytes`、`issues[]`。
成功时 `deleted` 为 `true`；文本模式形如：

```
Deleted profile: my_testkey_config
  Files: 12
  Bytes: 40960
```

> 与 TUI 一致：TUI 的配置管理器删除活动配置同样被拒绝
> （`config.active_delete_forbidden`），`--force` 只存在于 CLI。

### `config import` / `config import-legacy` / `config export` / `config migrate`

```
avbpowertool config import        [-h] [--json] archive
avbpowertool config import-legacy [-h] [--name PROFILE_ID] [--no-activate] [--json] archive
avbpowertool config export        [-h] [--output OUTPUT] [--json] profile
avbpowertool config migrate       [-h] [--profile PROFILE] [--json]
```

- `config import <archive>`：从 ZIP 归档导入配置。
  归档不存在 → `config.not_found`；非法 ZIP → `config.invalid_archive`；
  同名配置已存在 → `config.profile_exists`。`--json` 键：`profile_id`、`issues[]`。
- `config import-legacy <archive>`：导入 v1（AVBPowerTool 1.x）配置并自动转换为
  当前 schema。`--name PROFILE_ID` 指定新 id（默认从归档推导），
  `--no-activate` 不激活（默认**会激活**）。v1 BATCH 归档被明确拒绝
  （`import.legacy.batch_not_supported`）。`--json` 键：`profile_id`、
  `partition_count`、`key_count`、`issues[]`。
- `config export <profile>`：导出为 ZIP，`--output` 默认 `<profile>.zip`。
  `--json` 键：`output_path`、`issues[]`。导出内容为
  `manifest.json` + `profile.json` + `keys/**`（含 `.pem` 与 `.pem.bin`），**不含镜像**。
- `config migrate [--profile ID]`：把磁盘上的 v2 配置就地升级为 v3。
  v2 在读取时本就会在内存中自动迁移（文件不变），这个命令才把 v3 写回。
  `--json` 键：`profile_id`、`migrated`、`issues[]`。

### `keys` 子命令

```
avbpowertool keys list          [-h] [--profile PROFILE] [--json]
avbpowertool keys discover      [-h] [--profile PROFILE] [--merge | --replace] [--json]
avbpowertool keys ensure-public [-h] [--profile PROFILE] [--json]
avbpowertool keys add           [-h] --file NAME.pem [--profile PROFILE] [--json] key_id
avbpowertool keys remove        [-h] [--profile PROFILE] [--json] key_id
```

5 个子命令都接受 `--profile PROFILE`（默认 `current`，解析规则见第 3 节，
**宽容版**）。key store 目录不存在时报 `keys.directory_not_found`。

**`keys list`** —— 列出 manifest 中已注册的密钥，以及磁盘上**尚未注册**的 `.pem`。
`--json` 键：`keys[]`（`key_id` / `filename`）、`unregistered_pem_files[]`、`issues[]`。

**`keys discover`** —— 扫描 `keys/` 里的 `.pem`，把「文件名去掉 `.pem`」作为
key_id 写入 `manifest.json`。两种模式互斥：

| 旗标 | 语义 |
|---|---|
| `--merge`（**默认**） | 以磁盘上已有的 manifest 为基线。每个发现的 `.pem` 更新自己条目的 `private_key`；缓存的 `public_key` / `public_key_sha1` **仅在该条目的 `private_key` 文件名没变时**保留（换了文件说明缓存属于另一把密钥）。磁盘上已不存在 `.pem` 的条目**原样保留**，不会被删掉 |
| `--replace` | 旧的历史行为：manifest 完全由发现的 `.pem` 重建，所有缓存的 `public_key` 都被丢弃 |

`--json` 键：`discovered_count`、`retained_count`（保留的、没有对应 `.pem` 的
条目数）、`merged`、`manifest_entries[]`（`key_id` / `filename`）、`issues[]`。

**`keys ensure-public`** —— 为 manifest 中每个条目生成缺失的公钥文件
（`avbtool extract_public_key` 输出到 `<private_key>.pem.bin`，或条目里已有的
`public_key` 名字），并把 `public_key` 回写进 manifest。
私有密钥文件不存在 → 该条目记入 `skipped` 并报 `keys.private_key_missing`；
提取失败 → `keys.public_key_extract_failed`。
`--json` 键：`extracted[]`（`key_id` / `public_key`）、`skipped[]`、`issues[]`。

**`keys add <key_id> --file NAME.pem`** —— 往 manifest 加一条
`key_id -> 文件名` 映射。`--file` 是**key store 目录内**的私钥文件名
（**不会**从别处复制文件）。文件不存在 → `keys.file_not_found`；
key_id 已存在 → `keys.already_exists`。`--json` 键：`key_id`、`issues[]`。

**`keys remove <key_id>`** —— 从 manifest 删除条目（**不删除 `.pem` 文件**）。
不存在 → `keys.not_found`。`--json` 键：`key_id`、`issues[]`。

> **重要**：链式分区条目里的公钥文件必须是 `extract_public_key` 的产物
> （`*.pem.bin`）。avbtool 把 `chain_partition` 的第三段当**原始字节**读入，
> 传 `.pem` 会写坏 vbmeta。详见 [KEY_MANAGEMENT.md](KEY_MANAGEMENT.md)。

### `plugin` 子命令

```
avbpowertool plugin list      [-h] [--json]
avbpowertool plugin install   [-h] [--force] [--json] SOURCE
avbpowertool plugin uninstall [-h] [--yes] [--json] PLUGIN_ID
avbpowertool plugin run       [-h] [--json] PLUGIN_ID [-- <args> ...]
```

插件系统本身的完整说明（目录布局、清单 XML、打包方式、入口分派、环境变量契约、
安全性声明）见 [PLUGINS.md](PLUGINS.md)。本节只讲命令面。

**`plugin list`** —— 列出 `plugins/` 下的插件，按 id 排序。`name` 已按当前语言
（`settings.json` 的 `language`，默认 `en`）解析。没有插件时文本模式打印
`No plugins installed.`。文本模式在名字后带上清单里的版本：`v<version>`，若清单声明了
版本名则为 `v<version> (<version_name>)`。清单损坏的目录会出现在 `issues[]` 里
（`plugin.manifest_*`），但**不会**被静默丢弃。
`--json` 键：`plugins[]`（`plugin_id` / `name` / `entry` / `version` /
`version_name` / `path`）、`issues[]`。

**`plugin install <SOURCE>`** —— 从目录或 zip 安装。`SOURCE` 是插件目录或 `.zip`；
zip 支持「根布局」与「恰好一层目录」两种形状（后者即 `Compress-Archive` 的产物）。
目标 `plugins/<id>/` 已存在时由清单里的**版本**决定：

| 旗标 / 情况 | 语义 |
|---|---|
| 目标不存在 | 安装 |
| 待安装 `version` > 已安装 | 升级：直接覆盖，**不需要** `--force` |
| 待安装 `version` == 已安装 | 同版本重装：直接覆盖，**不需要** `--force` |
| 待安装 `version` < 已安装 | 拒绝降级：`plugin.downgrade`，退出码 1，**一个字节都不写** |
| 已安装清单读不出来 | `plugin.exists`，退出码 1（版本未知） |
| `--force` | 一律覆盖，含降级 |

因此 `--force` 的含义是「不管版本，强制覆盖」。清单里没有 `<version>` 就是版本 `0`；
`plugin.exists` 从此只用于「已安装清单缺失、损坏或声明的 id 与目录不符」这种版本无法
判断的兜底场景。
`--json` 键：`plugin_id`、`installed`、`file_count`、`version`、`version_name`、
`issues[]`（安装失败时 `version` / `version_name` 保持默认值 `0` / `""`）。
不安全归档（绝对路径 / 盘符 / `:` / `..`）在解压任何字节之前就被拒绝
（`plugin.install_failed`），不会留下半成品目录。

**`plugin uninstall <PLUGIN_ID>`** —— 删除 `plugins/<PLUGIN_ID>/` 整个目录。
`--yes` 是**硬门槛**：不给时 stderr 打印
`This deletes the plugin directory including any bundled files. Use --yes to confirm.`
并返回退出码 `1`，**不删除任何东西**（目录里可能带着密钥等材料）。
`--json` 键：`plugin_id`、`removed`、`removed_files`、`removed_bytes`（删除**之前**
统计的普通文件数与字节数）、`issues[]`。

**`plugin run <PLUGIN_ID> [-- <args…>]`** —— 用对应解释器运行插件的入口脚本
（`.py` → 当前解释器、`.ps1` → `pwsh -NoProfile -File`、`.cmd`/`.bat` → `cmd /c`、
`.sh` → `sh`）。工作目录 = 工作区根目录，环境变量见 [PLUGINS.md](PLUGINS.md#5-插件与工具的契约)。

参数透传规则（**第一个独立的 `--` 是分界线**）：

| 写法 | 结果 |
|---|---|
| `plugin run <id> --json` | `--json` 被**本工具**消费，输出一行结果 JSON |
| `plugin run <id> -- --json` | `--json` **原样透传**给插件，本工具不切换成 JSON 输出 |
| `plugin run <id> --json -- --json` | 两者同时成立：工具输出 JSON，插件收到 `--json` |
| `plugin run <id> -- --core --8e --no_prompt` | `--core --8e --no_prompt` 全部透传 |

> 这里没有用 `argparse.REMAINDER`：REMAINDER 会把 `plugin run <id> --json` 里的
> `--json` 也吃掉，无法同时满足前两行。实现在 `main()` 里按第一个 `--` 手工切分 argv
> （`_split_plugin_passthrough`），只对 `plugin run` 生效。

插件的 stdio **完全继承**（可交互），因此文本模式下插件成功运行时本工具**不额外输出
任何东西**；`--json` 也只描述本工具看到的结果，插件自己的 stdout/stderr 仍直接写到终端。
`--json` 键：`plugin_id`、`exit_code`、`issues[]`。

**退出码**：有 `issues[]`（插件没启动）→ `1`；没有 `issues[]` → **插件自己的退出码**，
原样透传（见第 2 节）。

### `about`

```
avbpowertool about [-h]
```

打印版本字符串（如 `AVBPowerTool 2.0.0.dev0`），退出码 0。不支持 `--json`。

---

## 5. 错误码清单

错误码稳定、点分前缀，由用例以 `OperationIssue` 元组返回（**不抛异常**）。
「退出码」列是 `exit_code_from_issues` 的映射结果。

### `config.*` → 退出码 1

| 错误码 | 含义 |
|---|---|
| `config.not_found` | 配置（或归档）不存在（`config delete` 也用它表示目标不存在） |
| `config.no_active_profile` | 请求 `current`/空，但没有活动配置 |
| `config.invalid_profile_id` | id 含非法字符（只允许字母、数字、`_`、`-`、`.`）；`config delete` 还会拒绝空、`.`、`..`、含路径分隔符、或解析后不是 `profiles/` 直接子目录的 id |
| `config.profile_exists` | 同名配置已存在 |
| `config.no_partitions` | 配置没有任何分区 |
| `config.invalid_field` | `config edit` 字段不在白名单，或值非法 |
| `config.invalid_algorithm` | `algorithm` 不是合法签名算法 |
| `config.invalid_option_combination` | 同一字段同时用 `--set/--unset` 与 `--append/--remove`；或 `use_persistent_digest` 未同时 `do_not_use_ab` |
| `config.partition_missing` | 分区不在配置中 |
| `config.profile_id_mismatch` | 目录名与 `profile.json` 的 `profile.id` 不一致，拒绝写入 |
| `config.auto_dir_not_found` | `--from-images DIR` 指向的目录不存在 |
| `config.missing_included_partition` | vbmeta 引用/链到一个不在配置里的分区 |
| `config.missing_image` | 分区 `image` 为空 |
| `config.missing_partition_name` | 分区缺少 `partition_name` |
| `config.missing_partition_size` | hash 分区既无 `partition_size` 也无 `dynamic_partition_size` |
| `config.invalid_partition_size` | `partition_size` 非法（非正 / 非 4096 倍数 / 过小） |
| `config.invalid_block_size` | `block_size` 不是正 2 的幂 |
| `config.invalid_fec_num_roots` | `fec_num_roots` 超出 2..255 |
| `config.invalid_chain_partition` | 链条目不是 `PART:SLOT:KEY_PATH` 或 SLOT < 1 |
| `config.invalid_prop` | `props` / `prop_from_file` 的键为空 |
| `config.duplicate_rollback_slot` | 多个链式分区占用同一 rollback slot |
| `config.vbmeta_no_contents` | vbmeta 既无 `included_partitions` 也无 `chain_partitions` |
| `config.cycle_detected` | vbmeta 依赖图存在环 |
| `config.missing_chain_partition` | 链式引用缺少对应分区 |
| `config.key_missing` | 分区的 `key_id` 为空，或 manifest 里找不到该 key_id |
| `config.missing_profile_id` / `config.missing_profile_name` | 配置 id / 名称缺失 |
| `config.invalid_schema_version` | `schema_version` 不受支持 |
| `config.parse_error` | `profile.json` 无法解析 |
| `config.invalid_archive` | 归档格式非法 |
| `config.import_failed` / `config.export_failed` | 导入 / 导出失败 |
| `config.create_failed` / `config.save_failed` / `config.migrate_failed` / `config.rename_failed` / `config.activate_failed` / `config.delete_failed` | 对应写盘操作失败（`config.delete_failed` 是 `config delete` 的 `rmtree` 失败，此时 `deleted` 为 `false`） |
| `config.load_error` | 读取配置失败 |
| `config.active_delete_forbidden` | 拒绝删除活动配置（`config delete` 加 `--force` 才允许） |
| `config.unsupported_descriptor` | 签名计划遇到不支持的描述符类型 |

### `keys.*` → 退出码 1

| 错误码 | 含义 |
|---|---|
| `keys.directory_not_found` | key store 目录不存在 |
| `keys.file_not_found` | `keys add` 指定的私钥文件不存在 |
| `keys.not_found` | `keys remove` 的 key_id 不在 manifest |
| `keys.already_exists` | `keys add` 的 key_id 已存在 |
| `keys.private_key_missing` | `ensure-public` 时条目对应的私钥文件缺失 |
| `keys.public_key_extract_failed` | 公钥提取失败（`ensure-public` / `check-chains`） |
| `keys.manifest_not_found` | `keys/manifest.json` 不存在 |
| `keys.manifest_read_error` | manifest 读取失败 |
| `keys.invalid_request` | `keys add` 缺少 key_id 或文件名 |
| `keys.invalid_entry` / `keys.empty_private_key` / `keys.empty_manifest` / `keys.missing_private_key` | manifest 校验问题 |

### `image.*` → 退出码 1

| 错误码 | 含义 |
|---|---|
| `image.not_found` | 镜像文件不存在 |
| `image.no_vbmeta_structure` | 镜像没有 AVB 结构（无 footer） |

### `chain.*` → 退出码 1

| 错误码 | 含义 |
|---|---|
| `chain.malformed_entry` | 链条目不是合法的 `PART:SLOT:KEYFILE` |
| `chain.key_file_missing` | 链条目指向的公钥文件不在 key store |
| `chain.key_mismatch` | 链条目公钥 SHA1 ≠ 被链分区实际签名密钥的公钥 SHA1 |
| `chain.chained_partition_unsigned` | 被链分区是 NONE（未签名），链校验无意义 |
| `chain.key_not_found` | 链解析时没有密钥能匹配描述符的公钥 SHA1（`config create --from-images` 会报此码但**不阻断创建**）。在 `config create --from-images` 里它是**信息性**的：只出现在 `chain_issues[]`（文本输出单独成段），**不单独导致失败**、不影响退出码；在 `config check-chains` 等命令里它仍然映射到退出码 1 |

### `plugin.*` → 退出码 1

| 错误码 | 含义 |
|---|---|
| `plugin.not_found` | `plugins/<id>/` 不存在（`plugin uninstall` / `plugin run` 的 id 没装） |
| `plugin.downgrade` | **新增**。`plugin install` 的 `<version>` 比已安装的低。什么都不写；用 `--force`（或将来在 TUI 里确认）才能降级 |
| `plugin.exists` | 目标插件已安装但**版本无法判断**（已安装清单缺失、损坏，或声明的 id 与目录不符），且没给 `--force` |
| `plugin.id_invalid` | 插件 id 非法：为空、`.`、`..`、含 `/` 或 `\`，或解析后不是 `plugins/` 的直接子目录 |
| `plugin.manifest_missing` | 安装源里找不到 `avbpowertool_plugin_config.xml`（目录或归档） |
| `plugin.manifest_invalid` | 清单 XML 无法解析、根元素名不对、`schema_version` 不受支持、id 为空、`<version>` 不是非负整数、或没有声明任何 `<name>` |
| `plugin.entry_missing` | 清单的 `<entry>` 为空 |
| `plugin.entry_invalid` | `<entry>` 含 `/` 或 `\`（试图指向插件目录之外） |
| `plugin.entry_not_found` | 清单指向的入口文件在插件目录里不存在（`plugin run`） |
| `plugin.install_failed` | 安装失败：`SOURCE` 既不是目录也不是合法 zip、归档含不安全成员（绝对路径 / 盘符 / `:` / `..`）、或复制/解压时报 `OSError` |
| `plugin.uninstall_failed` | 删除插件目录失败（例如 Windows 上文件被占用） |
| `plugin.run_failed` | 插件**根本没启动**：入口后缀不支持、解释器缺失、子进程无法创建。此时 `exit_code` 是占位的 `-1` |

> `plugin run` 的退出码是特例：以上任一 issue 出现 → 退出码 `1`；`issues[]` 为空时
> 返回**插件自己的退出码**（插件退出 3 就是 3），非 0 也不算工具错误。

### `tool.*` / `signing.*` → 退出码 3

| 错误码 | 含义 |
|---|---|
| `tool.execution_failed` | avbtool 子进程返回非 0 |
| `signing.step_failed` | 某个签名步骤失败 |

### 其它（退出码 0，除非同时出现上面类别的 issue）

| 错误码 | 含义 |
|---|---|
| `workspace.root_not_found` | 工作区根目录不存在 |
| `workspace.path_escape` | 路径逃逸出 `Images/` |
| `import.legacy.*` | v1 旧配置转换相关（`batch_not_supported`、`key_not_found`、`invalid_entry`、`partial_chain`、`unsupported_algorithm`、`block_size_conflict`、`failed`） |

---

## 6. 端到端示例

下面是一条**零手工改 JSON** 的完整流程：从镜像生成配置 → 硬编码链式分区、
改 flags / 密钥 / 算法 → 校验链 → 改名 → 导出。示例 id 为 `my_testkey_config`。

```shell
# 1) 一步生成配置 + 从镜像读回分区（镜像集合由包装脚本按旗标表算好）
avbpowertool config create --id 20260101-120000_testkey --name testkey \
  --from-images \
  --images boot,dtbo,init_boot,pvmfw,recovery,vendor_boot,vbmeta,vbmeta_system \
  --json

# 1b) 密钥：先放进 profiles/<id>/keys/*.pem，再发现 + 生成公钥
avbpowertool keys discover      --profile 20260101-120000_testkey --json
avbpowertool keys ensure-public --profile 20260101-120000_testkey --json

# 2) 硬编码链式分区（按分区名原地替换）+ vbmeta flags=1
avbpowertool config edit vbmeta --profile 20260101-120000_testkey --set flags=1 \
  --append chain_partitions=boot:3:testkey_rsa4096.pem.bin \
  --append chain_partitions=recovery:1:testkey_rsa4096.pem.bin \
  --append chain_partitions=vbmeta_system:2:testkey_rsa2048.pem.bin \
  --json

# 3) vbmeta_system 换成 2048 密钥 + SHA256_RSA2048
avbpowertool config edit vbmeta_system --profile 20260101-120000_testkey \
  --set key_id=testkey_rsa2048 --set algorithm=SHA256_RSA2048 --json

# 4) 剪掉不需要的内嵌描述符（--remove 对普通元组字段按整项匹配）
avbpowertool config edit vbmeta --profile 20260101-120000_testkey \
  --remove included_partitions=odm --json

# 5) 校验链式一致性（只读）
avbpowertool config check-chains --profile 20260101-120000_testkey --json

# 6) 改名（目录 id + 显示名）
avbpowertool config rename 20260101-120000_testkey my_testkey_config \
  --name "My testkey config" --json

# 7) 导出
avbpowertool config export my_testkey_config --output my_testkey_config.zip --json

# 8) 之后可以按需激活并试跑签名计划
avbpowertool config activate my_testkey_config
avbpowertool image sign boot vbmeta --dry-run --json

# 9) 清理：删除配置（破坏性，必须显式 --yes；活动配置还要 --force）
avbpowertool config delete my_testkey_config --yes --force --json
```

每一步都可以用退出码做门禁：

```powershell
function Invoke-Avb { param([string[]]$Args)
  & avbpowertool @Args
  if ($LASTEXITCODE -ne 0) { throw "avbpowertool failed: $($Args -join ' ') (exit $LASTEXITCODE)" }
}
Invoke-Avb @('config','check-chains','--profile','my_testkey_config','--json')
```

---

## 相关文档

- [创建配置](CONFIG_CREATION.md) —— 用 CLI / TUI / API 创建配置
- [密钥管理](KEY_MANAGEMENT.md) —— key store、manifest 与公钥文件要求
- [插件系统](PLUGINS.md) —— 插件目录布局、清单 XML、打包方式与环境变量契约
- [后端 API 参考](BACKEND_API.md) —— 在 Python 中调用同一批用例
- [README](README.md) —— 安装与快速开始
