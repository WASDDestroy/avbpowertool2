# 插件系统

AVBPowerTool2 的插件是一个**放在工作区 `plugins/<id>/` 里的目录**：一份清单 XML
加一个入口脚本。插件可以是一个打包好的 shell 脚本，也可以是任何能通过 CLI 反过来
驱动本工具的程序。

> 本页描述的是插件**作者**与插件**使用者**共同依赖的契约。CLI 命令面的逐条语法见
> [CLI 参考](CLI_REFERENCE.md)第 4 节 `plugin` 子命令。

## 目录

- [1. 目录布局](#1-目录布局)
- [2. 清单 XML 格式](#2-清单-xml-格式)
- [3. 打包与安装](#3-打包与安装)
- [4. 入口类型与分派](#4-入口类型与分派)
- [5. 插件与工具的契约](#5-插件与工具的契约)
- [6. 插件里怎么调用本工具](#6-插件里怎么调用本工具)
- [7. 安装 / 卸载 / 运行示例](#7-安装--卸载--运行示例)
- [8. TUI](#8-tui)
- [9. 安全性](#9-安全性)

---

## 1. 目录布局

```
<工作区根>/
  plugins/
    testkey_config_gen/                    <- 一个插件 = 一个目录
      avbpowertool_plugin_config.xml       <- 清单（文件名固定）
      make-testkey-config.cmd              <- 入口脚本（entry）
      make-testkey-config.ps1              <- 入口脚本用到的其它文件
      keys/
        testkey_rsa2048.pem                <- 插件自带的材料，随插件一起走
        testkey_rsa4096.pem
      README.md
```

- 插件 id 就是目录名。id 只允许字母、数字、`_`、`-`、`.`，且必须是 `plugins/` 的
  **直接子目录**，不允许路径分隔符（拒绝 `a/b`、`..`、绝对路径等）。
- **开发位置 = 安装位置**。`plugins/<id>/` 既是仓库里开发中的插件目录，也是安装后的
  目录；`plugin install` 从一个**别处**的目录或 zip 复制进这里，`plugin uninstall`
  直接删掉这个目录。因此把插件直接写进仓库的 `plugins/` 就等于「已经安装」。
- `plugins/` 下的子目录如果没有清单文件，就**不是**插件，会被 `plugin list` 忽略。
  有清单但清单不合法，则会被 `plugin list` **报告**（`issues[]`），不会被静默丢弃。
- 清单文件名固定为 `avbpowertool_plugin_config.xml`。

## 2. 清单 XML 格式

仓库里现成的例子（`plugins/testkey_config_gen/avbpowertool_plugin_config.xml`）：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<avbpowertool_plugin schema_version="1">
  <id>testkey_config_gen</id>
  <version>1</version>
  <version_name>1.0.0</version_name>
  <entry>make-testkey-config.cmd</entry>
  <names>
    <name lang="en">Test-key config generator</name>
    <name lang="zh">测试密钥配置生成</name>
  </names>
  <description lang="zh">按旗标表生成 testkey 打包配置并导出 zip</description>
  <description lang="en">Generate a testkey packaging config from the selected image set and export it as a zip</description>
</avbpowertool_plugin>
```

| 元素 / 属性 | 必填 | 说明 |
|---|---|---|
| 根元素 `avbpowertool_plugin` | 是 | 根元素名写错 → `plugin.manifest_invalid` |
| `schema_version`（属性） | 否 | 省略视为 `1`（当前唯一支持的版本）。不是数字或不是 `1` → `plugin.manifest_invalid` |
| `<id>` | 是 | 插件 id，**必须与安装目录名一致**（`plugin install` 用它决定复制到哪个目录）。为空 → `plugin.manifest_invalid`；含非法字符 → `plugin.id_invalid` |
| `<version>` | 否 | 插件版本的**单调递增整数**；省略视为 `0`（没有版本信息的老插件就是 v0）。不是非负整数（`-1`、`abc`、`1.5`）→ `plugin.manifest_invalid`。它决定升级 / 降级判断，见第 3 节 |
| `<version_name>` | 否 | **任意字符串**版本名（`1.1.0`、`2026 春节版`…），省略视为 `""`。不做任何格式校验，也**不参与版本比较**，只用于展示 |
| `<entry>` | 是 | 入口脚本的**裸文件名**，必须在插件目录内。为空 → `plugin.entry_missing`；含 `/` 或 `\`（想指向目录外）→ `plugin.entry_invalid` |
| `<names><name lang="…">` | 是 | 多语言显示名，至少一条。**一条都没有 → `plugin.manifest_invalid`** |
| `<description lang="…">` | 否 | 多语言描述，当前 CLI 不展示，供 TUI / 未来的列表界面使用 |

**语言解析规则**（`PluginManifest.name_for`）：

1. 精确匹配（大小写不敏感）请求的语言，例如请求 `zh` 命中 `lang="zh"`；
2. 退化为语言主标签，例如请求 `zh_CN` 命中 `lang="zh"`；
3. 回退到 `lang="en"`；
4. 再回退到清单里第一条非空的名字；
5. 都没有时用插件 id 兜底。

空文本的条目不算翻译，不会挡住后面的回退。清单里的多语言**不经过 gettext**：
插件自带自己的翻译，工具只是按当前语言挑一条。

当前语言来自工作区 `settings.json` 的 `language`（默认 `en`），由 `bootstrap()` 注入
给用例，因此 `plugin list` 的 `name` 已经按该语言解析好。

## 3. 打包与安装

```shell
avbpowertool plugin install <SOURCE> [--force] [--json]
```

`SOURCE` 可以是：

1. **目录** —— 目录里直接就是清单 + 入口，例如 `.\my_plugin\`。
   如果该目录**就是** `plugins/<id>/` 自己（原地安装），复制会变成空操作而不是报错。
2. **zip 归档** —— 支持两种布局：
   - **根布局**：清单就在压缩包根目录（`avbpowertool_plugin_config.xml`、`run.cmd`…）；
   - **恰好一层目录**：所有文件都在**同一个**顶层目录下（`demo/avbpowertool_plugin_config.xml`…），
     这正是 `plugin pack` 与 `Compress-Archive <目录>` 产生的形状。这一层目录名会被剥掉。

   归档里存在**多于一个**清单（例如根一份、子目录一份）→ `plugin.manifest_invalid`；
   一个都没有 → `plugin.manifest_missing`。

安装行为：

- 目标目录不存在 → 直接安装；
- 目标 `plugins/<id>/` 已存在时由**版本**决定（见下方「版本与降级」）：
  新版本或同版本**无需** `--force` 直接覆盖；旧版本 → `plugin.downgrade`；
- 给了 `--force` → 一律覆盖（含降级）；
- 已安装清单读不出来（缺失、损坏、或声明的 id 与目录不符）→ 版本无法判断，
  退回旧语义：没给 `--force` 就报 `plugin.exists`；
- zip 在**解压任何字节之前**先校验所有成员：绝对路径、盘符、`:`（NTFS ADS）、
  以及任何 `..` 段都会被拒绝（`plugin.install_failed`），因此不会出现「解压到一半」
  的半成品目录，也不会有文件落到目标目录之外；
- `SOURCE` 既不是目录也不是合法 zip → `plugin.install_failed`。

### 版本与降级

`<version>` 是**由插件作者自行维护的单调递增整数**——工具不会自己生成、自增或改写它。
`<version_name>` 是自由格式的展示用标签（`plugin list` 里显示成 `v2 (2.1.0)`），
**不参与任何比较**。

| 已安装 | 待安装 | 结果 |
|---|---|---|
| 无 | 任意版本 | 安装 |
| v1 | v2 | **升级**，直接覆盖安装，**不需要** `--force` |
| v2 | v2 | **同版本重装**，直接覆盖，**不需要** `--force` |
| v2 | v1 | **拒绝降级**：`plugin.downgrade`，退出码 1，**一个字节都不写** |
| v2 | v1 + `--force` | 执行降级 |
| 清单读不出来 | 任意版本 | `plugin.exists`（版本未知），需要 `--force` |
| 任意 | 任意 + `--force` | 覆盖 |

- 默认拒绝降级，因为降级会悄悄丢掉用户已经装上的修复与功能。错误消息里同时给出
  **两边的版本**（版本号与 `version_name`）并提示用 `--force`。
- `plugin.downgrade` 是**新增错误码**（退出码 1，与其它 `plugin.*` 一致）。它接管了
  「已安装」这一场景，`plugin.exists` 从此只表示「目录在，但版本无法判断」。
- 降级必须显式确认：CLI 上用 `--force`，或在 TUI 的降级询问里确认（见第 8 节）。
  在 TUI 里拒绝降级则一个字节都不写。
- 清单里**没有** `<version>` 就是版本 `0`，因此没有版本信息的老插件照常安装、照常升级，
  不会因为缺字段而装不上。
- 覆盖安装是**合并**语义（与 `--force` 一直以来的行为一致）：新包里没有的文件会留在原地。
  需要干净安装时先 `plugin uninstall <id> --yes` 再装。

### 打包（`plugin pack`）

```shell
avbpowertool plugin pack <SOURCE> [--output <ZIP>] [--json]
```

`SOURCE` 有两种用法（按此顺序解析）：

1. **插件目录路径** —— 存在且是目录就直接用它，例如 `.\plugins\testkey_config_gen\`；
2. **已安装插件的 id** —— 路径不存在时按 `<工作区>/plugins/<SOURCE>/` 查找，
   例如 `testkey_config_gen`。

两者都不满足 → `plugin.not_found`（退出码 1），消息里会说明这两种用法。

- **默认输出**：`<工作区根>/<plugin_id>.zip`，与 `config export` 的默认风格一致；
  `--output` 可指定其它路径。文件已存在时直接覆盖。
- **产物布局**：**恰好一层目录** `<plugin_id>/<相对路径>`，例如
  `testkey_config_gen/avbpowertool_plugin_config.xml`、
  `testkey_config_gen/keys/testkey_rsa4096.pem`。这正是 `plugin install` 支持的
  「恰好一层目录」形状，因此产物可以**直接安装**。
- **跳过的噪音文件**：任何层级的 `__pycache__/` 目录、`*.pyc`、`.git/` 都不进 zip；
  其余文件全部打包。插件自己的 `keys/` 也会打包——插件可以合法地携带密钥材料。
- **密钥提示**：源目录里存在 `keys/` 子目录（或任何 `.pem`）时，文本模式额外打印一行
  `包含密钥材料，会一起打包进 zip`；`--json` 里对应 `includes_key_material: true`，
  供脚本判断。
- 输出 zip 落在源目录内部时，该 zip 自身会被排除，重复打包不会自包含。
- 写包失败（父目录建不出来、磁盘错误、文件被占用等）→ `plugin.pack_failed`，
  且不会留下半成品 zip。

`--json` 键：`plugin_id`、`output_path`、`file_count`、`version`、`version_name`、
`includes_key_material`、`issues[]`。

`pack` → `install` 往返示例：

```shell
avbpowertool plugin pack testkey_config_gen
avbpowertool plugin install testkey_config_gen.zip
```

**手工打包（不推荐）**：优先用 `plugin pack`。确实要手工打包时，注意 zip 里必须是
「恰好一层目录」布局——在插件目录的**父目录**里执行，让 zip 带上目录名：

```powershell
# Windows PowerShell
Compress-Archive -Path .\my_plugin -DestinationPath .\my_plugin.zip -Force
```

```shell
# POSIX：在插件目录的父目录里执行
cd /path/to/parent
zip -r my_plugin.zip my_plugin
```

卸载：

```shell
avbpowertool plugin uninstall <PLUGIN_ID> --yes [--json]
```

`--yes` 是**硬门槛**：不给时工具只往 stderr 打印

```
This deletes the plugin directory including any bundled files. Use --yes to confirm.
```

并以退出码 1 结束，**不删除任何东西**（插件目录里可能带着密钥等材料，所以不做交互
式询问，只接受显式确认）。给了 `--yes` 后，`removed_files` / `removed_bytes` 描述的是
删除**之前**统计到的普通文件数量与字节数。id 非法 → `plugin.id_invalid`；
目录不存在 → `plugin.not_found`；删除失败（例如 Windows 上文件被占用）→
`plugin.uninstall_failed`。

## 4. 入口类型与分派

`entry` 的后缀决定用什么解释器运行（`infrastructure/plugins/runner.py`）：

| 后缀 | 实际执行的命令 |
|---|---|
| `.py` | `sys.executable <entry> <args…>`（**当前正在运行本工具的解释器**，因此虚拟环境内的依赖对插件可见） |
| `.ps1` | `pwsh -NoProfile -File <entry> <args…>` |
| `.cmd` | `cmd /c <entry> <args…>` |
| `.bat` | `cmd /c <entry> <args…>` |
| `.sh` | `sh <entry> <args…>`（**仅挂名**：代码路径存在，但未在 Windows 上验证过） |
| 其它 | 不支持 → `plugin.run_failed`（`exit_code` 为 `-1`） |

解释器本身找不到（例如没有 `pwsh`）→ `plugin.run_failed`。

## 5. 插件与工具的契约

插件进程由本工具直接拉起，契约如下：

| 项 | 值 |
|---|---|
| 工作目录（cwd） | **工作区根目录**（`WorkspacePaths.root`）。插件里写 `Images/`、`Logs/`、`profiles/` 等相对路径，含义与工具自身完全一致 |
| `AVBPOWERTOOL_ROOT` | 工作区根目录的绝对路径 |
| `AVBPOWERTOOL_PLUGIN_DIR` | 该插件自己的目录绝对路径（`plugins/<id>/`） |
| `AVBPOWERTOOL_PLUGIN_ID` | 插件 id |
| `AVBPOWERTOOL_LANG` | 当前语言代码（`en` / `zh`…），与 `plugin list` 解析显示名用的是同一个值 |
| `AVBPOWERTOOL_CLI` | 建议用来反向调用本工具的命令前缀，当前为 `uv run avbpowertool` |
| stdio | **继承父进程**：stdout / stderr / stdin 都不被捕获，插件可以打印进度、也可以交互式提问 |
| 退出码 | **原样透传**。插件退出 3，`avbpowertool plugin run` 就退出 3；非 0 退出码**不算错误**，`issues[]` 仍为空 |
| 参数 | `--` 之后的全部内容按原样追加到入口脚本之后，一个字符都不改 |

环境变量是在父进程环境之上**叠加**的（`PATH`、`HOME` 等照常可见），不是替换。

`exit_code` 为 `-1` 只出现在「插件根本没跑起来」的情况（id 非法、插件不存在、
`entry` 文件缺失、解释器缺失、清单非法），此时 `issues[]` 一定非空。**脚本应依据
`issues[]` 是否为空判断失败，而不是只看 `exit_code`** —— 因为插件自己也可以退出
`-1` 之外的非 0 状态，那些是插件的判断而非工具的错误。

参数透传规则（`plugin run` 专用）：

```shell
avbpowertool plugin run testkey_config_gen --json             # --json 给 avbpowertool
avbpowertool plugin run testkey_config_gen -- --json          # --json 给插件
avbpowertool plugin run testkey_config_gen -- --core --8e --no_prompt
```

- 第一个**独立的** `--` 之前的部分由本工具的 argparse 解析（`plugin_id`、`--json`）；
- `--` 之后的全部内容原样传给插件；
- 文本模式下插件成功运行时，本工具**不额外输出任何东西**（避免污染插件自己的
  输出）；只有 `--json` 时才会打印一行结果 JSON；
- 这一点没有用 `argparse.REMAINDER` 实现：REMAINDER 会把 `plugin run <id> --json`
  里的 `--json` 也吃掉，从而无法同时满足上面两种含义。实际做法是在
  `main()` 里按第一个 `--` 手工切分 argv（见
  `avbpowertool/presentation/cli/parser.py::_split_plugin_passthrough`）。

## 6. 插件里怎么调用本工具

**推荐做法：走 CLI。** 用 `$AVBPOWERTOOL_CLI`（或显式 `uv run --project
"$AVBPOWERTOOL_ROOT" avbpowertool …`）起一个新的工具进程：

```powershell
# 插件内部的 PowerShell 片段
$root = $env:AVBPOWERTOOL_ROOT
uv run --project "$root" avbpowertool config create --id "$id" --from-images --json
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

```python
# 插件内部的 Python 片段
import json
import os
import subprocess

root = os.environ["AVBPOWERTOOL_ROOT"]
proc = subprocess.run(
    ["uv", "run", "--project", root, "avbpowertool", "plugin", "list", "--json"],
    cwd=root,
    capture_output=True,
    text=True,
)
data = json.loads(proc.stdout)
```

好处是：命令面有文档、有退出码约定、有 `--json`，工具的稳定性承诺都覆盖它。

**另一种做法：直接 `import avbpowertool`**，调用内部的用例 / 领域模型：

```python
import os
import sys

sys.path.insert(0, os.environ["AVBPOWERTOOL_ROOT"])
from avbpowertool.application.commands import PluginListRequest
from avbpowertool.application.services.manage_plugins import PluginListUseCase
from avbpowertool.infrastructure.filesystem.workspace import WorkspacePaths

workspace = WorkspacePaths.discover(os.environ["AVBPOWERTOOL_ROOT"])
result = PluginListUseCase(workspace, language=os.environ["AVBPOWERTOOL_LANG"]).execute(
    PluginListRequest()
)
```

> **非稳定接口，属于取巧做法。** Python 层的模块路径、类名、构造函数签名、请求/结果
> 字段都不在兼容性承诺之内，重构随时可能改掉它们；只有 CLI 命令面是稳定的。除非确实
> 无法用 CLI 表达（例如需要在一个进程内复用已加载的对象），否则请用第 6 节上半部分的
> CLI 方式。这样做同时意味着插件与工具**共用同一个解释器环境**，依赖冲突要自己承担。

## 7. 安装 / 卸载 / 运行示例

```shell
# 列出已安装的插件（name 已按当前语言解析，版本显示为 v<version> [(<version_name>)])
avbpowertool plugin list
avbpowertool plugin list --json

# 打包成可安装的 zip（SOURCE 可以是插件目录路径，也可以是已安装插件的 id）
avbpowertool plugin pack ./my_plugin --json
avbpowertool plugin pack testkey_config_gen

# 从目录安装
avbpowertool plugin install ./my_plugin --json

# 升级（或同版本重装）：不需要 --force
avbpowertool plugin install ./my_plugin.zip --json

# 降级：默认拒绝，用 --force 显式确认
avbpowertool plugin install ./my_plugin.zip --force --json

# 运行：-- 之后是插件自己的参数
avbpowertool plugin run testkey_config_gen -- --core --8e --no_prompt
avbpowertool plugin run testkey_config_gen --json
avbpowertool plugin run testkey_config_gen --json -- --core

# 卸载（--yes 是硬门槛）
avbpowertool plugin uninstall my_plugin --yes --json
```

`--json` 输出形状：

| 命令 | 顶层键 |
|---|---|
| `plugin list` | `plugins[]`（`plugin_id` / `name` / `entry` / `version` / `version_name` / `path`）、`issues[]` |
| `plugin pack` | `plugin_id`、`output_path`、`file_count`、`version`、`version_name`、`includes_key_material`、`issues[]` |
| `plugin install` | `plugin_id`、`installed`、`file_count`、`version`、`version_name`、`issues[]` |
| `plugin uninstall` | `plugin_id`、`removed`、`removed_files`、`removed_bytes`、`issues[]` |
| `plugin run` | `plugin_id`、`exit_code`、`issues[]` |

> `plugin run` 的 `--json` 只描述**本工具**看到的结果：插件自己的 stdout/stderr 仍然
> 直接写到终端，不会进入 JSON。需要机器可读的插件输出时，请让插件自己写文件或输出
> 到 stderr。

## 8. TUI

TUI 里有一个**插件页**，可以运行、安装和卸载插件。入口路径：

```
Home
  [O] Other Features          <- route:misc
        [P] Plugins           <- action:plugin.manage
```

插件页是**一个选择器**，行内容按顺序是：

1. 每个已安装插件 —— `显示名 (插件id) v<版本>`，清单里声明了 `version_name` 时再追加
   `(<version_name>)`（显示名已按当前语言从清单解析，见第 2 节的语言解析规则）；
2. `安装插件…`；
3. `卸载插件…`。

清单损坏的插件排在这些行之后（见下）。

- **选择插件即运行**：选中插件行后出现一次确认，确认后立即运行该插件。
- **交互式插件会接管终端**：运行前 curses 被挂起（`def_prog_mode` + `endwin`），
  终端完全交给插件 —— 插件可以打印进度，也可以交互式提问；插件退出后 curses 状态被
  恢复（`reset_prog_mode` + 重绘），回到插件页。运行期间终端上没有 TUI 的边框和帮助
  行，这是正常的。
- **TUI 不能传参数**：从 TUI 运行插件时参数列表恒为空。需要参数请用 CLI：

  ```shell
  avbpowertool plugin run testkey_config_gen -- --core --8e --no_prompt
  ```

- **安装要输入路径**：TUI 没有文件浏览器，选 `安装插件…` 后会弹出一个输入框，请填写
  插件**目录**或 **zip 归档**的路径（即 `plugin install` 支持的两种来源）。直接回车
  （空行）或 Esc 取消，不会调用任何用例。安装是纯用例调用，**不会**挂起 curses ——
  它不启动子进程。
- **降级一定先问**：待安装的 `<version>` 比已安装的版本低时，插件页先展示
  `plugin.downgrade` 的完整消息（含**两边**的版本号与 `version_name`），然后才询问。
  确认后用 `force` 重试安装，结果页会注明「已按确认执行降级安装」；不确认则显示
  `已取消，未做任何改动。`，**一个字节都不写**。脚本化场景（CI、批处理）没有人在
  终端前回答，仍然用 `avbpowertool plugin install <目录|zip> --force`。
- **卸载要先选再确认**：选 `卸载插件…` 会打开第二个选择器列出已安装插件；选中后询问
  `卸载插件 <id> 吗？`，只有确认才会删除 `plugins/<id>/`。结果页给出删除的文件数与
  释放的字节数。没有任何插件时该入口只给出提示。
- **一个插件都没装时**：插件页先显示 `没有已安装的插件。`（以及清单 issue），然后
  **仍然提供安装与卸载入口**，不会变成一个死胡同。
- **清单损坏的插件**：清单无法解析的目录不会被静默丢弃，而是在列表页和结果页里以
  `[错误码] 消息` 逐条列出；这些行不是可运行的插件，选中它们只会显示这些消息。
- **运行结果**：结果页显示插件名/id、`退出码`，以及（若有）逐条 issue。**非 0 退出码
  不代表工具出错** —— 那是插件自己的判断；只有 `issues[]` 非空才说明插件根本没跑起来。
  安装/卸载的结果页则报告 `id`、`version`、文件数 / 字节数，失败时给出
  `[错误码] 消息` 行。

## 9. 安全性

**本工具不对插件做任何安全检查**：没有签名、没有权限模型、没有沙箱、没有来源校验。
`plugin install` 只是把目录/归档复制进 `plugins/<id>/`，`plugin run` 只是用解释器起
一个子进程 —— 插件拿到的是你的用户权限，能读写工作区里的一切（包括 `profiles/` 下的
私钥）。

真正被强制的只有**正确性**：

- 归档成员不能逃出目标目录（拒绝绝对路径、盘符、`:`、`..`）；
- 插件 id 永远是 `plugins/` 下的单个目录名；
- `entry` 永远是插件目录内的裸文件名，清单无法指向自己包外的脚本。

因此：**只安装和运行你信任的插件，安全性由用户自己负责。**

---

## 相关文档

- [CLI 参考](CLI_REFERENCE.md) —— `plugin` 子命令的语法、旗标与退出码
- [架构](ARCHITECTURE.md) —— 分层与依赖方向（插件相关代码的位置）
- [后端 API 参考](BACKEND_API.md) —— 在 Python 中调用同一批用例
- [密钥管理](KEY_MANAGEMENT.md) —— 插件里生成配置时会用到的 key store 约定
