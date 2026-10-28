# macOS ARM64 产品运行时

## 当前可用范围

2026-10-28，本机已链接完整的 ruyiJS 产品运行时 `dist/js`，架构为 ARM64。
现有 Python `Context` 通过 Unix socket 启动这个进程并执行真正的 SpiderMonkey
JavaScript；Window、DOM、事件循环和各 Web API 继续由项目的 C++ owner 安装。

实际输出：

```python
ctx.eval("1 + 2")                                  # 3
ctx.eval("document.createElement('div').tagName")   # 'DIV'
ctx.eval("globalThis === window")                  # True
ctx.set("value", 21)
ctx.eval("value * 2")                              # 42
```

当前是 **macOS 27+ / Apple Silicon 实验版**。源码开发布局仍使用 Homebrew；
[本地 wheel](macos-arm64-wheel.md) 已内嵌 Python、OpenSSL 与网络依赖，并通过拒绝访问
Homebrew/仓库的隔离安装验证。PyPI 已发布的包仍只支持 Windows。

## 在当前仓库运行

从项目根目录执行：

```sh
PYTHONPATH=python python3.13 - <<'PY'
from ruyijs import Context

with Context() as ctx:
    print(ctx.eval("1 + 2"))
    print(ctx.eval("document.createElement('div').tagName"))
PY
```

完整验证入口：

```sh
python3.13 -B tools/verify_macos_runtime.py
```

验证脚本先检查真实 Python API，再运行整个本地回归套件；没有产品二进制时会失败。
最新验证记录为 `build/macos-arm64/runtime-verification.json`，测试日志为
`build/macos-arm64/logs/runtime-tests.log`。

HTTP/HTTPS（HTTP/1.1、HTTP/2、HTTP/3）与 WebTransport 现已接通，网络验证见下文链接。
网络组件构建、代理及证书配置见[网络说明](macos-arm64-network.md)。

## 已验证的行为

37 项测试全部通过，包含通信层单元测试及真实产品端到端测试：

- JavaScript 数值、Unicode、BigInt、状态保持、Context 进程隔离。
- Window/DOM、Python 回调、原生函数包装、构造调用和 JavaScript 异常恢复。
- Promise 微任务、逻辑时钟和定时器。
- URLPattern 的参数提取及 SpiderMonkey 正则匹配。
- SHA-256、AES-GCM 标准向量与篡改拒绝、AES-CBC、HMAC 标准向量。
- P-256/P-384/P-521 的 ECDSA 签名验证及 ECDH 共享密钥。
- CoreText 字体测量与文字绘制、ImageIO PNG 解码、直接绘图及 ImageBitmap 的 RGBA 像素。
- gzip、deflate、deflate-raw、Brotli 原生压缩/解压往返。
- `put_resource()` 配合离线 fetch、Blob Worker 消息交换、Worker 终止。
- 无限脚本超时后关闭 Context；父进程被杀死后，忙循环 Worker 退出。
- 启动失败返回子进程退出码和 stderr，避免将初始化错误隐藏成连接超时。

`navigator.platform` 实测为 `MacIntel`，这是参考 Firefox 158 在 Apple Silicon 上返回的
兼容性字符串；二进制架构由 `lipo` 验证为 `arm64`。

## 从第二阶段产物重建

先完成[引擎与生成数据构建](macos-arm64-build.md)。随后执行：

```sh
python3.13 -B tools/capture_firefox_baseline.py
python3.13 -B tools/build_macos_dependencies.py
python3.13 -B tools/build_macos_runtime.py --jobs 4
python3.13 -B tools/link_macos_runtime.py
python3.13 -B tools/verify_macos_runtime.py
```

基线采集会启动隔离的 Firefox 158，并打开本机临时 HTTP 页面。产品的 Location
配置要求规范的 HTTP(S) URL，因此不能使用 `about:blank` 作为这份构建基线。
采集的自动化状态原样保留，仍标记 `publishable_default_profile=false`。

构建入口编译 1,274 个单元（含 shell 接入单元），按源码、命令和实际头文件依赖
缓存对象。Windows 后端保留在条件编译分支；macOS 对应实现使用 POSIX、CoreText、
CoreGraphics/ImageIO 和 OpenSSL。链接器先生成候选文件，检查 ARM64 架构后替换 `dist/js`。

### Rust 与原生依赖

URLPattern 继续使用 Firefox 固定版本中的 `urlpattern 0.6.0`；正则回调仍进入
SpiderMonkey。`native/urlpattern/` 只实现既有 C ABI，不添加另一个 URLPattern JS owner。

Mozilla 原 Rust 库隐藏了部分标准库符号，独立链接第二份 Rust 静态库会产生冲突。
`integrate_runtime_rust.py` 根据 `config/rust-runtime-overlay.json` 校验原文件哈希，
向构建缓存中的 `jsrust` 加入本地 FFI 依赖，然后使用 Mozilla 原构建链重新生成
`libjsrust.a`。整个产品共用这一套 Rust 运行时。

这会对 `build/upstream/firefox-158.0/` 中的两份 Rust 输入及 Cargo.lock 产生受控修改；
原始/准备后哈希和最终库哈希记录在 `runtime-rust.json`，不修改已下载的源码归档。
后续产品重建应使用上述第三阶段入口。

Brotli 从同一锁定 Mozilla 源码构建。macOS zlib 通过原有压缩适配接口接入；加密
后端链接 `/opt/homebrew/opt/openssl@3/lib/libcrypto.dylib`，当前没有把该动态库捆绑进产品。

`config/macos-runtime.json` 区分两个版本约束：C++ 浮点 `from_chars` 要求 macOS 26；
本机 OpenSSL bottle 要求 macOS 27，所以当前最终可执行文件以 27 为最低链接目标。
降低系统要求需要替换数值转换依赖或构建兼容的依赖库，并在目标系统实际测试。

## 证据文件

| 文件 | 内容 |
| --- | --- |
| `build/macos-arm64/runtime-compile.json` | 完整产品编译清单与失败计数 |
| `build/macos-arm64/native-dependencies.json` | Brotli、Rust 和 OpenSSL 库身份 |
| `build/macos-arm64/runtime-rust.json` | 受控 Rust 源码修改和单一 Rust 库身份 |
| `build/macos-arm64/runtime-link.json` | 完整链接命令、架构、依赖与二进制哈希 |
| `build/macos-arm64/runtime-verification.json` | 真实 `Context.eval()` 结果及 37 项回归结果 |

## 尚未完成

- **公网 QUIC / 协议一致性**：Neqo 桥接与本地真实 UDP、Context HTTP3/WebTransport 已验证；当前环境的公网 UDP 被拒绝，跨实现互操作与完整 Firefox 指纹一致性尚未验收。
  当前 HTTP1 桥接是依据既有 ABI 重建的实现，不能据此宣称完整 Gecko 网络语义或指纹一致。
- **完整 Firefox 行为/像素一致性**：CoreText/ImageIO 后端仅完成上述功能验证，彩色
  字形、复杂动画图片、所有字体配置及指纹一致性尚未逐项对照验收。
- **原项目已有缺项**：例如 `ReadableStream.pipeThrough`、Blob 直接创建 ImageBitmap
  不在当前已实现能力内；回归使用已有 reader/writer 和 HTMLImageElement 路径。
- **诊断扩展**：官方 donor 没有原作者的 `StandaloneTrace`。构造器诊断记录仅在 donor
  提供该扩展时启用；原生函数包装已通过 JSAPI 实现并验证。
- **发布与跨平台回归**：本地 wheel 已捆绑动态库并完成 ad-hoc 签名；新机器/VM 测试、
  Developer ID 签名/公证、较早 macOS、Windows 原生回归和 macOS C ABI 客户端尚未完成。

当前成果是第三阶段的首个可运行里程碑：真实的 Python → 原生运行时 → JavaScript
链路已经建立，HTTP/HTTPS 网络组件也已接入。Neqo/H3 和 WebTransport 已接入，本地 wheel 已通过隔离安装验证；后续仍需完成公网互操作、正式发布及完整兼容性验收。
