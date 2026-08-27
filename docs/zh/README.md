# AVBPowerTool2

> [English](/README.md) | 中文版

AOSP `avbtool.py` 的配置驱动 Python 封装。提供 CLI 和 TUI 用于 Android Verified Boot 镜像签名、检查和配置管理。

## 功能特性

- **镜像检查**：读取 boot、system、vbmeta 镜像的 AVB 元数据
- **镜像签名**：使用 hash/hashtree footer 签名镜像，生成 vbmeta 镜像
- **配置管理**：基于 Profile 的配置，支持通过 ZIP 归档导入/导出
- **旧版配置导入**：将 v1（AVBPowerTool 1.x）配置 zip 自动转换为 v2（设置页或 `config import-legacy`）
- **密钥管理**：每个 Profile 独立的密钥库，基于 manifest 的密钥解析
- **CLI 模式**：功能完整的命令行界面，支持 `--json` 输出
- **TUI 模式**：基于 curses 的交互式终端界面，支持键盘导航
- **国际化**：通过 gettext 支持英文和中文本地化
- **跨平台**：Windows、Linux、macOS（支持 WSL）

## 快速开始

### 前置条件

- Python 3.11+
- 密钥操作（签名、公钥导出）满足以下任一条件即可：
  - 安装可选的 `crypto` extra（推荐——无需任何外部工具）
  - PATH 中存在可用的 `openssl` 命令行工具

内嵌的 `avbtool.py` 优先使用进程内的
[cryptography](https://cryptography.io/) 包；未安装时自动回退到 `openssl`
子进程（回退发生时会打印一次提示）。设置 `AVB_CRYPTO_BACKEND=openssl`
可强制使用回退路径。

内嵌 `avbtool.py` 的全部本地补丁（加密后端、纯 Python FEC）记录在
[VENDORED_AVBTOOL_PATCHES.md](VENDORED_AVBTOOL_PATCHES.md)，
升级上游 avbtool 时可据此重新打补丁。

### 安装

```shell
# 克隆仓库
git clone https://github.com/WASDDestroy/AVBPowerTool2.git
cd AVBPowerTool2

# 使用 uv 安装（推荐）
uv sync

# 或安装开发工具（测试、Lint、类型检查）
uv sync --all-extras
```

#### 使用 pip3 安装（无需 uv）

`uv` 并非必需——本包完全可以使用标准 Python 工具链（`python3` + `pip3`）
安装和运行。加密、FEC 以及（Windows 上）TUI 所需的依赖都是核心依赖，
`pip3` 会自动安装。

```shell
# 1) 创建并激活虚拟环境（推荐）
python3 -m venv .venv
source .venv/bin/activate            # Linux / macOS
# .venv\Scripts\Activate.ps1         # Windows (PowerShell)
# .venv\Scripts\activate.bat         # Windows (cmd)

# 2) 升级 pip 并安装本包（从源码目录进行可编辑安装）
python -m pip install --upgrade pip
python -m pip install -e .
# 或安装普通副本到 site-packages：
# python -m pip install .

# 3) 验证安装
python -m avbpowertool about
```

> **PATH 未配置？** `pip3` 会把 `avbpowertool` 可执行文件放到 Python 环境的
> `bin`/`Scripts` 目录。如果该目录不在 `PATH` 中，可以用
> `python -m avbpowertool` 替代——行为完全一致，且不依赖 `PATH`。

### CLI 用法

```shell
# 检查镜像 AVB 元数据
avbpowertool image inspect boot vbmeta

# 签名计划（dry-run）
avbpowertool image sign boot --dry-run

# 执行签名
avbpowertool image sign boot --execute --yes

# 配置管理
avbpowertool config list
avbpowertool config show
avbpowertool config validate
avbpowertool config activate myprofile
avbpowertool config import myconfig.zip
avbpowertool config import-legacy mylegacy_v1.zip   # 旧版 v1 配置自动转换为 v2
avbpowertool config export myprofile

# 关于
avbpowertool about
```

所有命令支持 `--json` 以获得机器可读的输出。

> 未使用 `uv`，或控制台脚本不在 `PATH` 中时，请在命令前加 `python -m`：
>
> ```shell
> python -m avbpowertool image inspect boot vbmeta
> python -m avbpowertool config list
> ```

### TUI 用法

```shell
# 启动交互模式（不带命令时默认行为）
avbpowertool
# 或未配置控制台脚本的 PATH 时：
python -m avbpowertool
```

### 后端 API（在 Python 中调用）

安装完成后，可直接在 Python 代码中导入并调用本包，无需任何控制台入口。
请在项目根目录运行（当前目录即工作区根目录，包含 `avbtool.py`、
`Images/`、`profiles/`）：

```python
# inspect.py — 使用 python inspect.py 运行
from avbpowertool.bootstrap import bootstrap
from avbpowertool.infrastructure.avbtool.runner import SubprocessAvbTool
from avbpowertool.application.commands import InspectImagesRequest
from avbpowertool.application.services.inspect_images import InspectImagesUseCase

ws = bootstrap()  # 工作区根目录 = 当前目录
avb = SubprocessAvbTool(ws.avbtool_script)
result = InspectImagesUseCase(ws, avb).execute(
    InspectImagesRequest(image_names=("boot", "vbmeta"))
)
for img in result.images:
    print(f"{img.image_name}: {img.descriptor}, {img.algorithm}")
```

也可以直接在 shell 中执行单行命令：

```shell
python -c "from avbpowertool.bootstrap import bootstrap; print(bootstrap().root)"
```

完整参考见 [后端 API 参考](BACKEND_API.md)。

## 项目结构

```
avbpowertool/
  domain/           纯模型、验证、签名计划（无 I/O）
  application/      用例、端口（Protocol 接口）
  infrastructure/   avbtool 子进程、文件系统、持久化、FEC
  presentation/     CLI (argparse) 和 TUI (curses)
  resources/        导航配置
  locale/           gettext 翻译文件 (.po)
  vendor/           内置 FEC 编码器
tests/
  unit/             单元测试
  integration/      集成测试
  contract/         契约/Schema 测试
  fixtures/         测试夹具
```

## 架构

四层六边形架构：

```
CLI / TUI
    |
    v
应用层（用例、请求/结果类型、进度事件）
    |
    v
领域层（模型、验证、签名计划、依赖图）
    ^
    |
基础设施层（avbtool 子进程、文件系统、持久化、FEC）
```

- `domain/` 不从其他层导入
- `application/` 仅依赖领域层和端口（Protocol）
- `infrastructure/` 实现端口
- `presentation/` 仅调用应用层用例

## 配置

### Profile 结构

```
profiles/
  <profile_id>/
    profile.json      v2 schema 配置
    keys/
      manifest.json   key_id -> 文件名映射
      *.pem           密钥文件
```

### 配置 v2 Schema

```json
{
  "schema_version": 2,
  "profile": {"id": "example", "name": "示例"},
  "key_store_path": "keys",
  "partitions": {
    "boot": {
      "image": "boot.img",
      "descriptor": "hash",
      "algorithm": "SHA256_RSA4096",
      "key_id": "release_rsa4096",
      "partition_name": "boot",
      "rollback_index": 0,
      "salt": "abcdef123456"
    }
  }
}
```

## 开发

参见 [AGENTS.md](../../AGENTS.md) 了解开发规范。

## 文档

- [实现计划](IMPLEMENTATION_PLAN.md) — 架构和阶段分解
- [后端 API 参考](BACKEND_API.md) — 在 Python 中调用后端
- [添加导航](FRONTEND_NAVIGATION.md) — 在 TUI 导航树中添加条目
- [编辑页面](FRONTEND_PAGES.md) — 创建或修改 TUI 视图
- [旧版配置导入](LEGACY_CONFIG_IMPORT.md) — v1 → v2 转换设计与实现

## 许可证

参见 [LICENSE](../../LICENSE)。
