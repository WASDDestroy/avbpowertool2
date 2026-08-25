# 内置 `avbtool.py` — 补丁登记文档

本文档记录内置的 [`avbtool.py`](../../avbtool.py) 相对 AOSP 上游原版所做的全部本地补丁，
目的是**在上游 avbtool 升级时能够快速重新打补丁、更新核心实现**。

- 上游基线：**AOSP avbtool 1.3.0**（`AVB_VERSION_MAJOR/MINOR/SUB = 1/3/0`，
  与 `libavb/avb_version.h` 保持同步）。
- 原版快照保留在仓库根目录：[`avbtool_reference.py`](../../avbtool_reference.py)。
- 打过补丁的版本：[`avbtool.py`](../../avbtool.py)。

## 目录

1. [约定](#约定)
2. [补丁清单](#补丁清单)
3. [PATCH-CRYPTO：进程内 cryptography 后端](#patch-crypto进程内-cryptography-后端)
4. [PATCH-FEC：纯 Python FEC 编码器回退](#patch-fec纯-python-fec-编码器回退)
5. [上游新版本的重新打补丁流程](#上游新版本的重新打补丁流程)
6. [验证清单](#验证清单)

## 约定

每个补丁位置都用包含字符串 `PATCH: AVBPowerTool2` 的注释标记。查找所有补丁点：

```shell
grep -n "PATCH: AVBPowerTool2" avbtool.py   # 应恰好有 6 处
```

查看与参考快照的完整差异：

```shell
git diff --no-index --no-prefix avbtool_reference.py avbtool.py
```

所有补丁共同遵守的设计规则：

- **只回退，不替换。** 上游原有代码路径（通常是 `openssl(1)` 或外部工具的子进程
  调用）始终保留，在快速/进程内路径不可用时使用。补丁是对上游代码的包裹或分支，
  不做删除。
- **不在 `avbtool.py` 顶部新增 import。** 所有第三方导入都是惰性的（函数内导入），
  保证该文件仅靠 Python 标准库即可独立运行。
- **输出逐字节兼容。** 补丁代码产生的签名、哈希、镜像字节必须与上游完全一致。

## 补丁清单

| 编号 | 用途 | 挂载点 | 回退方式 |
|---|---|---|---|
| PATCH-CRYPTO | 用 `cryptography` 包执行 RSA 密钥操作，替代调用外部 `openssl` | `RSAPublicKey.__init__`、`RSAPublicKey.sign`、`verify_vbmeta_signature` | 原有的 `openssl` 子进程调用（任一异常触发进程内永久降级） |
| PATCH-FEC | 通过 `avbpowertool.vendor.fec_encoder` 计算/生成 FEC 数据，替代 Android `fec` 二进制工具 | `calc_fec_data_size`、`generate_fec_data` | 原有的 `fec` 工具子进程调用（捕获 `ImportError`） |

## PATCH-CRYPTO：进程内 cryptography 后端

### 动机

上游所有 RSA 操作都通过命令行工具 `openssl` 完成，要求它已安装且能在 `PATH`
中找到。第三方 [`cryptography`](https://cryptography.io/) 包是项目的强制依赖，
因此密钥操作默认改为进程内执行——更快，且不依赖外部工具。

逃生开关：设置环境变量 `AVB_CRYPTO_BACKEND=openssl` 可强制走原生子进程实现
（用于对比两个后端，或在排查问题时排除进程内后端）。

### 新增的模块级辅助函数

插入在 `CERT_USAGE_UNLOCK` 常量之后、`class AvbError` 之前
（avbtool 1.3.0 中约第 66 行）。模块作用域不新增任何 import：

```python
_CRYPTOGRAPHY_USABLE = None  # None: undecided, True: usable, False: fallback


def _use_cryptography():
  """Return True if the in-process cryptography backend should be used.

  The import is deliberately lazy ('import on demand'): avbtool.py stays
  runnable without the third-party package, CLI start-up pays no import
  cost when no key operations are performed, and the decision is cached
  for the lifetime of the process.
  """
  global _CRYPTOGRAPHY_USABLE
  if _CRYPTOGRAPHY_USABLE is None:
    if os.environ.get('AVB_CRYPTO_BACKEND', '').strip().lower() == 'openssl':
      _CRYPTOGRAPHY_USABLE = False
    else:
      try:
        import cryptography  # noqa: F401

        _CRYPTOGRAPHY_USABLE = True
      except Exception:
        _CRYPTOGRAPHY_USABLE = False
  return _CRYPTOGRAPHY_USABLE


def _downgrade_to_openssl(exc):
  """Permanently switch this process back to the openssl subprocess."""
  global _CRYPTOGRAPHY_USABLE
  if _CRYPTOGRAPHY_USABLE is not False:
    sys.stderr.write(
        'avbtool: cryptography backend unusable (%s: %s); '
        'falling back to openssl subprocess.\n' % (type(exc).__name__, exc))
  _CRYPTOGRAPHY_USABLE = False


def _cryptography_load_public_numbers(key_path):
  """Return RSAPublicNumbers for a PEM file with a private or public key."""
  from cryptography.hazmat.primitives import serialization

  with open(key_path, 'rb') as f:
    data = f.read()
  try:
    private_key = serialization.load_pem_private_key(data, password=None)
  except Exception:
    # Not a readable private key - retry as a public key. This mirrors the
    # openssl implementation's '-pubin' retry for public-key-only files.
    public_key = serialization.load_pem_public_key(data)
    return public_key.public_numbers()
  return private_key.private_numbers().public_numbers


def _cryptography_modulus(key_path):
  """Read the RSA modulus from |key_path| (replaces 'openssl rsa -modulus')."""
  return _cryptography_load_public_numbers(key_path).n


def _cryptography_sign_raw(key_path, padded_data):
  """Apply the raw RSA private-key operation to already-padded data.

  Replaces 'openssl rsautl -sign -raw': |padded_data| is expected to be
  the complete PKCS#1 v1.5 padded block, so no additional padding is
  applied here - matching the historical byte-for-byte behaviour.
  """
  from cryptography.hazmat.primitives import serialization

  with open(key_path, 'rb') as f:
    data = f.read()
  private_key = serialization.load_pem_private_key(data, password=None)
  numbers = private_key.private_numbers()
  n = numbers.public_numbers.n
  m = int.from_bytes(bytes(padded_data), 'big')
  if m >= n:
    raise ValueError('Padded data block is larger than the RSA modulus')
  signature_int = pow(m, numbers.d, n)
  key_num_bytes = (n.bit_length() + 7) // 8
  return signature_int.to_bytes(key_num_bytes, 'big')


def _cryptography_verify_raw(modulus, exponent, sig_blob, expected_em):
  """Verify a raw RSA signature against an expected padded block.

  Replaces the 'openssl asn1parse -genconf' + 'openssl rsautl -verify
  -pubin -raw' pair: computing sig^e mod n over the embedded public-key
  blob makes the DER construction unnecessary.
  """
  sig_len = len(sig_blob)
  em = pow(int.from_bytes(bytes(sig_blob), 'big'), exponent, int(modulus))
  return em.to_bytes(sig_len, 'big') == bytes(expected_em)
```

共享状态（`_CRYPTOGRAPHY_USABLE`）语义：

| 取值 | 含义 |
|---|---|
| `None` | 尚未判定；首次使用时惰性判定 |
| `True` | `cryptography` 可导入且未被禁用 → 使用进程内后端 |
| `False` | 使用 openssl 子进程；对进程剩余生命周期是粘性的 |

`_cryptography_*` 辅助函数内部抛出的任何异常都会触发
`_downgrade_to_openssl(exc)`（stderr 打印一次性提示），此后**同一进程内的所有**
后续密钥操作都改用 openssl。

### 挂载点 1/3 — `RSAPublicKey.__init__`（模数提取）

定位锚点：`class RSAPublicKey` 内，上游以下列语句开头的代码块：
`args = ['openssl', 'rsa', '-in', key_path, '-modulus', '-noout']`。

将上游函数体替换为：先尝试 `_cryptography_modulus()`；出现任何异常则降级，
并落入保持原样的上游 openssl 流程（包括对纯公钥 PEM 文件的 `-pubin` 重试）：

```python
    # PATCH: AVBPowerTool2 - use in-process cryptography when available,
    # fall back to the historical openssl(1) subprocess.
    modulus_int = None
    if _use_cryptography():
      try:
        modulus_int = _cryptography_modulus(key_path)
      except Exception as exc:
        _downgrade_to_openssl(exc)
    if modulus_int is not None:
      modulus_hexstr = '%x' % modulus_int
    else:
      args = ['openssl', 'rsa', '-in', key_path, '-modulus', '-noout']
      p = subprocess.Popen(args,
                           stdin=subprocess.PIPE,
                           stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
      (pout, perr) = p.communicate()
      if p.wait() != 0:
        # Could be just a public key is passed, try that.
        args.append('-pubin')
        p = subprocess.Popen(args,
                             stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
        (pout, perr) = p.communicate()
        if p.wait() != 0:
          raise AvbError('Error getting public key: {}'.format(perr))

      if not pout.lower().startswith(self.MODULUS_PREFIX):
        raise AvbError('Unexpected modulus output')

      modulus_hexstr = pout[len(self.MODULUS_PREFIX):]

    # ... 上游后续代码不变：
    self.key_path = key_path
    self.modulus = int(modulus_hexstr, 16)
```

注意进程内结果被转换回同一个 `modulus_hexstr` 变量，下游逻辑完全不感知。
（上游假定指数恒为 65537；进程内辅助函数虽然从密钥读取真实指数，但此处只消费
`.n`，与上游行为一致。）

### 挂载点 2/3 — `RSAPublicKey.sign`（裸签名）

定位锚点：`RSAPublicKey.sign` 中**未指定自定义 `signing_helper` 程序**时才走的
`else:` 分支，紧邻上游 spawn `openssl rsautl -sign -raw` 的位置。在该处插入
进程内签名尝试；自定义 signing-helper 程序保持最高优先级，绝不会被拦截：

```python
        # PATCH: AVBPowerTool2 - apply the raw private-key operation
        # in-process when cryptography is available; the block handed to
        # us is already PKCS#1 v1.5 padded, exactly like 'rsautl -raw'.
        if _use_cryptography():
          try:
            signature = _cryptography_sign_raw(self.key_path,
                                               padding_and_hash)
          except AvbError:
            raise
          except Exception as exc:
            _downgrade_to_openssl(exc)
          else:
            if len(signature) != algorithm.signature_num_bytes:
              raise AvbError('Error signing: Invalid length of signature')
            return signature
        p = subprocess.Popen(
            ['openssl', 'rsautl', '-sign', '-inkey', self.key_path, '-raw'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)
```

行为契约：

- `padding_and_hash` 从上游代码传入时已完成 PKCS#1 v1.5 填充；辅助函数只执行
  裸运算 `pow(m, d, n)`——与 `rsautl -raw` 语义完全一致。
- 签名长度按 `algorithm.signature_num_bytes` 校验，与上游 openssl 路径随后的校验相同。
- 加载/使用密钥时抛出的 `AvbError` 直接向上传播（属于面向用户的错误）；其他任何
  异常先降级到 openssl，再经子进程重跑。

### 挂载点 3/3 — `verify_vbmeta_signature`

定位锚点：模块级函数 `verify_vbmeta_signature(vbmeta_header, vbmeta_blob)`。
上游在此通过 ASN.1 配置重建公钥 DER，再运行 `openssl rsautl -verify -pubin -raw`。
把整个上游代码块包进 `if verified is None:`，并优先尝试进程内校验：

```python
  # PATCH: AVBPowerTool2 - compute sig^e mod n in-process when cryptography
  # is available; this replaces both the 'asn1parse -genconf' DER public-key
  # construction and the 'rsautl -verify -pubin -raw' invocation below.
  verified = None
  if _use_cryptography():
    try:
      verified = _cryptography_verify_raw(modulus, exponent, sig_blob,
                                          padding_and_digest)
    except Exception as exc:
      verified = None
      _downgrade_to_openssl(exc)

  if verified is None:
    # ... 整个上游 openssl 函数体，缩进一层，结尾的比较改为记录结果而非提前返回：
    ...
        verified = (pout == padding_and_digest)

  if not verified:
    sys.stderr.write('Signature not correct\n')
    return False
  return True
```

被包裹的上游函数体内有两处结构性修改：

1. 整段 `asn1_str` / 临时文件 / 两次 `Popen` 序列整体缩进到
   `if verified is None:` 之下——其余内容不变。
2. 上游结尾为 `if pout != padding_and_digest: ... return False` /
   `return True`；补丁改为记录 `verified = (pout == padding_and_digest)`，
   并把 "Signature not correct" 的最终判定移到包裹层之后，使两个后端共用同一条退出路径。

这里的公钥来自 vbmeta blob 本身（模数从内嵌 blob 解析，指数由上游硬编码为
`65537`），因此辅助函数接收 `(modulus, exponent)` 而不是密钥文件路径。

## PATCH-FEC：纯 Python FEC 编码器回退

### 动机

上游通过调用 Android `fec` 工具二进制来计算前向纠错（FEC）数据，而典型开发机
（尤其 Windows）上没有该工具。项目自带
[`avbpowertool/vendor/fec_encoder.py`](../../avbpowertool/vendor/fec_encoder.py)
——跨平台 RS(255, N) 编码器（numpy 快速路径 + reedsolo 回退，二者均为包的强制依赖）。
两个被补丁的函数都先尝试 Python 实现，失败再回退外部工具。

### 挂载点 1/2 — `calc_fec_data_size`

定位锚点：模块级函数 `calc_fec_data_size(image_size, num_roots)` 的函数体最顶部
（`fec --print-fec-size` 子进程调用之前）：

```python
  # PATCH: AVBPowerTool2 — try Python FEC encoder first
  try:
    from avbpowertool.vendor.fec_encoder import calc_fec_data_size as _py_calc_fec
    return _py_calc_fec(image_size, num_roots)
  except ImportError:
    pass
  # ... 上游函数体保持不变，接在其后
```

### 挂载点 2/2 — `generate_fec_data`

定位锚点：模块级函数 `generate_fec_data(image_filename, num_roots)` 的函数体
最顶部（`tempfile` / `fec --encode` 子进程流程之前）：

```python
  # PATCH: AVBPowerTool2 — try Python FEC encoder first
  try:
    from avbpowertool.vendor.fec_encoder import generate_fec_data as _py_fec
    return _py_fec(image_filename, num_roots)
  except ImportError:
    pass
  # ... 上游函数体保持不变，接在其后
```

### 行为说明

- 只有 `ImportError` 会回退到外部 `fec` 工具。若 `fec_encoder` 能导入但 numpy 和
  reedsolo 都未安装（正常情况下不会发生：二者均为强制依赖），它会抛出
  `RuntimeError("No FEC encoding method available...")` 并直接传播。
- 导入解析依赖 Python 将**脚本所在目录**放在 `sys.path` 首位：runner 以
  `[sys.executable, <workspace>/avbtool.py]` 方式调用，而 `avbtool.py` 与
  `avbpowertool/` 包同级，因此 `avbpowertool.vendor.fec_encoder` 可以解析。
  若把 `avbtool.py` 单独拷贝到远离包的位置，导入会抛出 `ImportError`，
  自动改用外部 `fec` 工具。
- Python 版 `calc_fec_data_size` 是纯算术运算
  （`num_roots * ceil(image_size / chunk_size)`），与 `fec` 工具打印的大小精确一致。

## 上游新版本的重新打补丁流程

1. 将新版上游脚本保存为 `avbtool_reference.py`（替换旧快照），并原样复制一份为
   `avbtool.py`。
2. 若基线版本号变化，同步更新本文档顶部的基线记录。
3. 先打 **PATCH-FEC**（两处小插入，分别位于 `calc_fec_data_size` 和
   `generate_fec_data` 函数体顶部——按函数名定位，不要按行号）。
4. 再打 **PATCH-CRYPTO**：
   1. 在 `CERT_USAGE_UNLOCK` 常量之后插入辅助函数块。
   2. 给 `RSAPublicKey.__init__` 的模数解析打补丁。
   3. 给 `RSAPublicKey.sign` 的无 signing-helper 分支打补丁。
   4. 按上文方式包裹 `verify_vbmeta_signature` 的 openssl 函数体。
5. 执行下方验证清单。
6. 将两个文件连同更新后的本文档一起提交（行号提示可能漂移；符号锚点不应漂移）。

如果上游重构了某个锚定函数（重命名、拆分、逻辑变化），请重新阅读上游周边代码，
在遵守设计规则的前提下调整挂载方式：保证原路径仍可达、import 保持惰性、
补丁处保留 `# PATCH: AVBPowerTool2 ...` 标记。

## 验证清单

```shell
# 1. 恰好存在六个补丁标记
grep -c "PATCH: AVBPowerTool2" avbtool.py          # 期望：6

# 2. 与参考快照的差异只落在本文记录的区域
git diff --no-index --stat avbtool_reference.py avbtool.py

# 3. 包测试（含 test_avbtool_fec_patch_exists 冒烟测试）
uv run pytest tests/

# 4. 加密后端冒烟：
uv run python avbtool.py version
$env:AVB_CRYPTO_BACKEND='openssl'; uv run python avbtool.py version  # 强制回退路径仍可运行
```

大版本重打补丁后建议再做一次功能核对：分别用两个后端各签一次镜像
（设置与不设置 `AVB_CRYPTO_BACKEND=openssl`），确认输出逐字节一致；用 Python
编码器生成 FEC 数据，并在 `fec` 工具可用的环境下与其输出比对。
