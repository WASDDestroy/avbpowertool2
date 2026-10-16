# plugins/testkey_config_gen/ —— testkey 打包包装脚本（插件）

`make-testkey-config.cmd` / `make-testkey-config.ps1` 把「6 步 OEM 测试密钥
（testkey）配置打包流程」封装成一次调用：按旗标表算出镜像集合 → 安装
本插件自带的 / `--key-dir` 指定的两把 testkey → 从镜像生成配置 → 写死链式分区 /
flags / 密钥 / 算法 → 剪枝内嵌描述符 → 自检 → （可选）改名 → （可选）导出 zip →
（可选）签名 dry-run 预览。

**本脚本只生成配置，不签名、不写 `Images/`。** 真正的签名要另外显式执行
`image sign ... --execute --yes`。

> **本目录同时是插件安装位置。** 插件按 `plugins/<id>/` 布局安装（本插件
> `id = testkey_config_gen`），清单见 `avbpowertool_plugin_config.xml`，
> `entry` 指向 `make-testkey-config.cmd`。因此脚本不能假设「自己的父目录就是仓库根」，
> 仓库根与密钥目录都靠下面的**定位规则**解析。
>
> `keys/` 里的 testkey PEM 是本地密钥材料，被 `.gitignore` 的
> `plugins/*/keys/` 规则排除，**不入库**；清单 XML、两个脚本与本文档都在版本控制内。

## 前置条件

| 条件 | 说明 |
|---|---|
| PowerShell 7+ | 脚本头部是 `#Requires -Version 7.0`；`.cmd` 启动器用 `pwsh` 调用 |
| `uv` 在 `PATH` 上 | 所有 CLI 调用都是 `uv run avbpowertool ...` |
| 能定位仓库根 | 见下「仓库根定位」；仓库根要有 `avbtool.py` 与 `profiles/` |
| 仓库根有 `Images/` | 里面放待打包的 `*.img` |
| 能定位密钥目录 | 见下「密钥目录定位」；目录里要有 `testkey_rsa4096.pem` 与 `testkey_rsa2048.pem`，会被拷进 `profiles/<id>/keys/`（覆盖同名文件） |

任何一项缺失，脚本在**创建任何东西之前**以退出码 1 结束。

## 仓库根定位

脚本在 `plugins/testkey_config_gen/` 下，`tools/` 时代那种「脚本目录的父目录 = 仓库根」
的假设已经不成立，因此改为：

1. 显式给了 `--repo-root <dir>`：规范化该路径，**要求目录里存在 `avbtool.py`**，
   否则报错并以退出码 1 结束；
2. 没给：**从脚本所在目录逐级向上查找**，取第一个**同时含 `avbtool.py` 与 `profiles/`**
   的目录作为仓库根；
3. 一路查到盘符根都没有 → 报错并以退出码 1 结束，提示用 `--repo-root` 指定。

所以脚本可以在**任意 cwd**（含 `%TEMP%`）下用绝对路径调用，不必先 `cd` 到仓库根。

## 密钥目录定位

1. 显式给了 `--key-dir <dir>`：要求该目录存在且**同时含两把 PEM**，否则报错退出 1；
2. 没给：按顺序探测，取第一个同时含 `testkey_rsa4096.pem` 与 `testkey_rsa2048.pem`
   的目录：

   | 顺序 | 目录 | 说明 |
   |---|---|---|
   | 1 | `<脚本目录>/keys` | 本插件的密钥目录（默认命中） |
   | 2 | `<脚本目录>` | 密钥直接放在插件根 |
   | 3 | `<仓库根>/for_agents` | 迁移前的旧位置，保留向后兼容 |

3. 三个都没有 → 报错并以退出码 1 结束，提示用 `--key-dir` 指定。

解析结果同时用于第 0 步前置检查与第 3 步的拷贝。

## 用法

```bat
:: 从仓库根（或任意 cwd，脚本自己会定位仓库根）
plugins\testkey_config_gen\make-testkey-config.cmd --core --8e
```

```powershell
# 直接调 PowerShell 脚本（参数完全一样）
pwsh -NoProfile -File plugins\testkey_config_gen\make-testkey-config.ps1 --no_prompt --no_export

# 任意 cwd + 绝对路径也可以
pwsh -NoProfile -File F:\GitHub\avbpowertool2\plugins\testkey_config_gen\make-testkey-config.ps1 --no_prompt

# 显式指定密钥目录
pwsh -NoProfile -File plugins\testkey_config_gen\make-testkey-config.ps1 --key-dir D:\testkeys
```

因为 ps1 自己解析 `--flag`，`.cmd` 不做任何参数翻译，`%ERRORLEVEL%` 原样透传。

## 旗标表

### 镜像集合旗标（**互斥**，最多给一个；一个都不给等价于 `--no_hashtree_core`）

| 旗标 | 镜像集合 |
|---|---|
| `--no_hashtree_core`（默认） | `boot, dtbo, init_boot, pvmfw, recovery, vendor_boot, vbmeta, vbmeta_system` |
| `--no_hashtree_oplus` | 上面 + `vbmeta_vendor` |
| `--core` | 上面 + `odm, product, system, system_ext, system_dlkm, vendor, vendor_dlkm`，**若 `Images/odm_dlkm.img` 存在**则再加 `odm_dlkm` |
| `--mi` | `--core` 的集合 + `mi_ext` |
| `--oplus` | `--core` 的集合 + `my_product, my_manifest, my_bigball, my_carrier, my_engineering, my_heytap, my_region, my_stock`，**若 `Images/my_preload.img` / `Images/my_company.img` 存在**则各自追加 |

> `--8e` 可以**与上面任意一个共存**；`no_hashtree_core / no_hashtree_oplus /
> core / mi / oplus` 之间互斥，给两个及以上 → 用法错误，退出码 2。

条件项（`odm_dlkm` / `my_preload` / `my_company`）**只在镜像存在时加入**，
缺失不算错误；非条件项缺失 → 一次性列出所有缺失镜像并退出 1，**不创建任何东西**。

### 其它旗标

| 旗标 | 语义 |
|---|---|
| `--8e` | 额外追加 `data_ext`（可与任意集合旗标共存） |
| `--no_prompt` | 跳过第 7 步的交互改名 |
| `--no_export` | 跳过导出 zip |
| `--no_sign_preview` | 跳过末尾的签名 dry-run 预览 |
| `--force` | 允许复用已存在的同名 `profiles/<id>/`（跳过创建，但继续拷密钥 / 发现 / 生成） |
| `--id <v>` | 配置 id，默认 `<yyyyMMdd-HHmmss>_testkey`（24 小时制） |
| `--name <v>` | 配置显示名，默认等于 id |
| `--images a,b,c` | 显式镜像集合。**给出时忽略集合旗标**（仍做存在性检查）；名字可带或不带 `.img` |
| `--output <dir>` | 导出目录，默认仓库根（导出到 `<dir>\<id>.zip`） |
| `--repo-root <dir>` | 仓库根。显式给出时必须含 `avbtool.py`；不给则从脚本目录向上查找（见上） |
| `--key-dir <dir>` | 存放两把 testkey PEM 的目录。不给则按 `<脚本目录>/keys` → `<脚本目录>` → `<仓库根>/for_agents` 顺序探测（见上） |
| `-h`, `--help` | 打印用法 |

`--flag value` 与 `--flag=value` 两种写法都接受。未知参数 → 用法错误 + usage，退出码 2。

> **`--images` 的注意点**：第 5 步会**无条件**把 `boot:3` / `recovery:1` /
> `vbmeta_system:2` 三条链写进 `vbmeta`，并给 `vbmeta` / `vbmeta_system` 设
> flags 与 2048 密钥。所以 `--images` 里至少要包含 `boot`、`recovery`、
> `vbmeta`、`vbmeta_system`；否则第 6 步自检会报
> `config.missing_included_partition`（`vbmeta` 链到一个不在配置里的分区）并以
> 退出码 1 结束——这是有意的：脚本宁可报错，也不产出一个链是悬空的配置。

> **厂商（OEM）签名的镜像**：这类 `vbmeta` 内嵌的链式公钥通常不在密钥库里，
> 第 4 步会把它们记进 `chain_issues`（信息性，**不影响退出码**），脚本会打印
> 一条 `[提示]` 说明有 N 条链式公钥未找到；这不是失败——第 5 步会用上面那三条
> 硬编码 testkey 链覆盖掉，第 6 步的 `config check-chains` 照常通过。

## 默认值

| 项 | 默认值 |
|---|---|
| `--id` | `<yyyyMMdd-HHmmss>_testkey`，如 `20260101-120000_testkey` |
| `--name` | 等于 `--id` |
| `--repo-root` | 从脚本所在目录向上找到的第一个同时含 `avbtool.py` 与 `profiles/` 的目录 |
| `--key-dir` | 第一个同时含两把 PEM 的目录：`<脚本目录>/keys` → `<脚本目录>` → `<仓库根>/for_agents` |
| `--output` | `--repo-root` |
| 镜像集合 | `--no_hashtree_core` |

## 示例

```bat
:: 1) 默认：基础 8 个分区，走完改名 / 导出 / 预览
plugins\testkey_config_gen\make-testkey-config.cmd

:: 2) 核心 + 8e（含 odm_dlkm / data_ext），不交互、直接出 zip
plugins\testkey_config_gen\make-testkey-config.cmd --core --8e --no_prompt

:: 3) 只写配置，不导出、不预览（给 CI / 批处理用）
plugins\testkey_config_gen\make-testkey-config.cmd --no_prompt --no_export --no_sign_preview

:: 4) 复用已存在的 profile 目录（保留其密钥库，替换分区集合）
plugins\testkey_config_gen\make-testkey-config.cmd --id 20260101-120000_testkey --force --no_prompt

:: 5) 显式指定密钥目录
plugins\testkey_config_gen\make-testkey-config.cmd --key-dir D:\testkeys --no_prompt
```

## 退出码

| 退出码 | 触发条件 |
|---|---|
| `0` | 成功 |
| `1` | 前置条件不满足（含定位不到仓库根 / 密钥目录）、镜像缺失、profile 目录已存在且没给 `--force`、或任意一步 CLI 返回非 0（原样透传 CLI 的退出码，通常也是 1） |
| `2` | 用法错误：未知参数、集合旗标互斥、缺参数值 |

失败时脚本会打印 CLI `--json` 输出里的 `issues[].error_code` + `message`。

## 脚本做了什么（10 步）

0. 前置检查（`avbtool.py` / `Images/` / testkey 密钥目录 / `uv`），并解析仓库根与密钥目录
1. 按旗标表算镜像集合，检查存在性；profile 目录冲突检查
2. `config create --id <id> --name <name> --allow-empty --json`（仅在目录不存在时）
3. 把两把 PEM 从解析出的密钥目录拷进 `profiles/<id>/keys/` → `keys discover` → `keys ensure-public`
4. `config create --id <id> --from-images --overwrite --images <集合> --json`（保留密钥库；
   解析不到的链式公钥只记入 `chain_issues`，信息性、不影响退出码，脚本打印一条 `[提示]`）
5. `config edit`：`vbmeta` 的 `flags=1` + 三条链式分区、`vbmeta_system` 换
   `testkey_rsa2048` / `SHA256_RSA2048`、其余分区 `key_id=testkey_rsa4096`、
   `vbmeta` / `vbmeta_system` 的 `included_partitions` 剪枝（幂等）
6. 自检：`config validate` + `config check-chains` 都必须退出 0
7. （可跳过）交互改名 `config rename`，之后步骤都用新 id
8. （可跳过）`config export <id> --output <output>\<id>.zip`
9. （可跳过）`image sign <全部分区> --profile <id> --dry-run --json`，
   打印每步的 `operation` / `partition_name` / `command`（**只读，不写盘**）
10. 收尾摘要：profile id、分区数、链式条目、zip 路径、后续可用命令

## 产物与副作用

- `profiles/<id>/`（含 `keys/`、`profile.json`）
- `<output>\<id>.zip`（除非 `--no_export`）
- `Logs/`（CLI 自己的运行日志）

**不写 `Images/`**，不回显密钥内容。整个流程用 `try/finally` 恢复原始工作目录。

## 相关文档

- [CLI 参考](../../docs/zh/CLI_REFERENCE.md) —— 完整命令面、退出码与错误码
- [密钥管理](../../docs/zh/KEY_MANAGEMENT.md) —— key store、manifest 与公钥文件要求
- [创建配置](../../docs/zh/CONFIG_CREATION.md) —— 用 CLI / TUI / API 创建配置
