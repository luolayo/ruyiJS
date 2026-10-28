# macOS ARM64 wheel

## 当前结果

2026-10-28，已生成可离线安装的本地实验包：

`wheelhouse/ruyijs-0.1.6-py3-none-macosx_27_0_arm64.whl`

约 53 MiB，要求 **macOS 27+、Apple Silicon、原生 ARM64 Python 3.10+**。
当前实际安装验证使用独立的 CPython 3.14.10；网络辅助进程使用包内 CPython 3.13.18。
二者不共用 site-packages，也不要求宿主 Python 安装 requests、cryptography、h2 或 Necko。

这是本地构建产物，未上传 PyPI，未完成 Developer ID 签名和 Apple 公证。
所有 Mach-O 文件均已作 ad-hoc 签名，并校验为 ARM64。

## 安装与使用

从仓库目录安装生成的 wheel：

```sh
python3 -m venv /tmp/ruyijs-demo
/tmp/ruyijs-demo/bin/python -m pip install --no-index --no-deps \
  wheelhouse/ruyijs-0.1.6-py3-none-macosx_27_0_arm64.whl
cd /tmp
/tmp/ruyijs-demo/bin/python - <<'PY'
from ruyijs import Context
with Context() as ctx:
    print(ctx.eval('1 + 2'))
    print(ctx.eval("document.createElement('div').tagName"))
PY
```

预期输出为 `3` 和 `DIV`。安装和首次启动不下载浏览器、Python 或其他运行时组件。
运行已安装版本时，不需要配置 `RUYIJS_SHELL`、`RUYIJS_NECKO_PYTHON`、`PYTHONPATH`
或 `DYLD_LIBRARY_PATH`。

Windows wheel 的平台选择和原有固定 ZIP 下载路径保留；本次未运行 Windows 原生回归。
恢复了原打包入口依赖、但曾被删除的 `tools/wheel_runtime.py`。

## 包内布局和依赖

```text
ruyijs/
  _runtime/
    dist/js
    lib/libcrypto.3.dylib
    vendor/necko-derived/
      bin/python3
      lib/python3.13/
        site-packages/necko/          # NSS / NSPR / Neqo 与桥接库
        site-packages/ruyijs_necko/   # 网络辅助程序、Brotli
        site-packages/...            # 固定版本的第三方依赖
    licenses/
    runtime-manifest.json
    SHA256SUMS
```

- 引擎是前几阶段构建的真实产品 `dist/js`；仅对包内副本修改依赖路径和签名。
- 内嵌 Python 使用 `python-build-standalone` 的固定发布归档；不复制开发 venv。
- 原 Homebrew OpenSSL 被复制到包内，并替换引擎的绝对动态库引用。
- 扫描全部 27 个 Mach-O 文件，将非系统依赖改为 `@loader_path` 相对路径，
  清除旧 RPATH，拒绝缺失依赖、错误架构或高于 wheel 标签的最低系统版本。
- NSS/NSPR、softoken、freebl 继续来自锁定的 Firefox 158；Neqo 为 0.31.1。
- 辅助进程的 15 个第三方 Python 包通过固定版本及 wheel SHA256 安装。
  移除不需要的 pip、编译头文件、静态库和带临时绝对 shebang 的命令行脚本。
- 保留 CPython/其静态依赖、Mozilla、Rust、OpenSSL 和 Python 包的许可证文本。
  完整 Python 发布归档提供 install-only 归档中省略的第三方许可证。
- 外层 wheel `RECORD`、内嵌 Python 包 `RECORD` 和运行时 `SHA256SUMS` 均对应打包后的文件。
  `runtime-manifest.json` 记录源产物、解释器、包版本、Mach-O 依赖和签名状态。

主要固定输入：

| 文件 | 内容 |
| --- | --- |
| `config/python-macos.lock.json` | 内嵌 Python、许可证归档及验证用宿主 Python 的 URL、大小、SHA256 |
| `config/macos-wheel.lock.json` | wheel 平台、最低系统版本、OpenSSL 原始库和许可证哈希 |
| `config/necko-macos-requirements.txt` | 辅助 Python 的依赖版本及 wheel 哈希 |
| `config/macos-wheel-build-requirements.txt` | 独立 PEP 517 构建器依赖版本及哈希 |

## 构建与复验

先按现有构建说明准备 `dist/js` 和网络辅助组件，再执行：

```sh
python3.13 -B tools/build_macos_wheel.py
python3.13 -B tools/verify_macos_wheel.py
```

构建器会下载并校验固定的 Python 发布归档，生成
`build/macos-arm64/wheel-runtime`，随后在临时源码树和独立构建环境中通过 PEP 517 构建。
它不会重置当前仓库，也不会修改现有 `dist/js` 或开发用网络 venv。

只改 Python 包装层/元数据时，可使用 `--reuse-runtime` 复用已校验的运行时快照；
修改引擎、网络辅助源码或依赖后，应重新运行完整构建，不使用该选项。
下游已有准备好的目录时，也可设置 `RUYIJS_BUILD_MACOS_RUNTIME`，交给标准 PEP 517
入口消费；此变量只用于打包，不用于运行。

## 隔离验证的证据与边界

验证器在仓库外创建包含空格的临时路径，解包固定的 CPython 3.14.10，并创建全新 venv。
它清空运行时覆盖、Python 路径和动态库路径变量，设置最小系统 PATH。

1. 在禁止网络访问的子进程中用 `pip --no-index --no-deps` 安装 wheel；保留 pip 默认的
   bytecode 编译行为，验证嵌套 CPython 标准库也能正常安装。
2. macOS 沙箱禁止客户端及其所有子进程读取仓库、`/opt/homebrew` 和 `/usr/local`；
   实际打开开发引擎与 Homebrew OpenSSL 文件必须返回 `PermissionError`。
3. 校验外层 wheel RECORD、运行时文件哈希、执行位、ARM64 架构、动态库路径和代码签名。
4. 运行 17 项安装后测试：真实 eval/DOM、Python 回调、URLPattern、Worker、超时清理、
   Canvas/图片、压缩、WebCrypto，以及 HTTP/H2/H3/WebTransport 和证书拒绝。
5. 整体搬迁安装目录，再验证解释器独立性、eval 和 5 项真实网络测试。
6. 执行 pip uninstall，确认包含内嵌运行时的包目录被移除。

网络服务端在独立进程中运行，客户端只能经真实 TCP/UDP 访问；客户端不读取服务端代码。
安装测试不访问公网，HTTP3/WebTransport 使用本地 Neqo 服务端。因此，本次结果证明
**本机上摆脱仓库和 Homebrew 的独立安装/搬迁运行**，不代表已经完成另一台物理 Mac、
全新 macOS VM、Gatekeeper 下载隔离、公网 QUIC 或跨实现互操作验收。

| 记录 | 内容 |
| --- | --- |
| `build/macos-arm64/wheel-build.json` | wheel 路径、大小、SHA256、运行时清单哈希 |
| `build/macos-arm64/wheel-verification.json` | 隔离安装、17+5 项测试、搬迁、卸载和限制 |
| `build/macos-arm64/logs/wheel-offline-install.log` | 禁网、无依赖的 pip 安装日志 |
| `build/macos-arm64/logs/wheel-installed-tests.log` | 17 项已安装运行时测试 |
| `build/macos-arm64/logs/wheel-relocated-network.log` | 搬迁后的 5 项网络测试 |
| `wheelhouse/*.whl.sha256` | 对应 wheel 的校验文件 |

最低版本暂不降到 macOS 26 或更早：当前产品和所用 OpenSSL 构建要求 macOS 27。
后续发布工作包括新机器/VM 测试、正式签名/公证、Windows 回归与 CI、许可证/源码发布清单复核。

参考：[Python standalone 归档说明](https://gregoryszorc.com/docs/python-build-standalone/main/distributions.html)、
[PyPA wheel 格式](https://packaging.python.org/en/latest/specifications/binary-distribution-format/)。

CI 的双 VM 构建/安装流程及产物说明见 [macOS ARM64 CI](macos-arm64-ci.md)。
