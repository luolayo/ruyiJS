# macOS ARM64 网络接入

## 当前结果

2026-10-28，现有 `Context.navigate()` 和 `fetch()` 已能通过辅助进程发起真实
HTTP/HTTPS 请求。验证覆盖 HTTP/1.1、HTTP/2、HTTP/3 和 WebTransport，TLS 使用
NSS 3.130 / NSPR 4.40；QUIC/HTTP3 使用 Firefox 158 所带的 Neqo 0.31.1。

本次外部验证：`https://example.com/` 返回 200、577 字节，协商 TLS 1.3、ALPN `h2`。
通过 `Context.navigate()` 得到 `document.title === 'Example Domain'`，导航记录的
`nextHopProtocol === 'h2'`。

HTTP3 / WebTransport 已通过本机真实 UDP 服务端验证，包含 `Context.navigate()`、
`fetch()`、JS `WebTransport` 和辅助进程清理。公网 HTTP3 尚未验证成功：两个公开站点
经系统 DNS 解析到 `198.18.*` 后，UDP 返回 `Connection refused`；用 DNS-over-HTTPS
得到 `www.cloudflare.com` 的 `104.16.123.96` 并保留原主机名校验证书，仍返回相同错误。
没有关闭证书校验、修改系统代理或用 TCP 降级结果冒充 HTTP3 成功。

当前仍是 macOS 27 / ARM64 实验版；已生成携带全部运行时依赖的本地 wheel，
见 [wheel 打包与隔离安装验证](macos-arm64-wheel.md)，尚未发布。

## 实现来源与范围

- Python 网络代码和 Firefox 根证书数据恢复自 SHA256 锁定的正式 ruyiJS 0.1.5 wheel。
  来源记录在 `native/necko/source-manifest.json`，修改后的输入哈希在构建报告中。
- NSS、NSPR、softoken、freebl 使用已锁定 Firefox 158 macOS 发行包中的原生库。
  运行网络请求不会启动 Firefox 浏览器；动态库复制在隔离辅助环境内。
- 原自定义 `necko_core` C++ 源码没有在公开仓库或 wheel 中找到。`native/necko/`
  根据现有 ctypes ABI 重建了 POSIX socket、HTTP/1 framing 和 NSS 回调 I/O 桥接。
- HTTP/2 继续使用原 Python 层的 hyper-h2、HPACK 和连接管理。
- `native/necko/quic/` 重建 `necko_quic_call` 的 JSON ABI，直接调用 Neqo 的 HTTP3/
  WebTransport API；没有自实现 QUIC。库为原生 ARM64 `libnecko_quic.dylib`，只在网络
  辅助进程中加载，不并入 SpiderMonkey 的 Rust 静态库。
- 每条 QUIC 连接由原 Python 协议线程独占，Rust 使用线程本地连接表和全局唯一句柄。
  Rust 复制 Python UDP 描述符的所有权，连接关闭时释放副本，原描述符仍由 Python 管理。
  收发循环有批次上限，避免 UDP 流量阻塞取消。
- 证书链/主机名验证沿用原方案：cryptography 配合 Firefox 根证书及约束数据，
  并非 Firefox 的完整 mozpkix 验证流程。

因此，当前结果说明真实联网链路可用，**不表示原 Gecko 网络栈或 Firefox TLS 指纹
已逐字节复现**。TCP TLS profile 为 `ruyijs-macos-nss-defaults`，
QUIC TLS profile 为 `ruyijs-macos-neqo-defaults`。

## 构建与验证

先完成现有 ARM64 引擎和产品构建。QUIC 测试额外使用 Homebrew `nss` 包的
`certutil` / `pk12util` 生成临时测试证书库（`brew install nss`）；测试服务端运行时
仍加载 Firefox 158 的固定 NSS 库，Homebrew NSS 不进入产品运行时。

从项目根目录执行：

```sh
python3.13 -B tools/build_macos_network.py
python3.13 -B tools/build_macos_runtime.py --jobs 4
python3.13 -B tools/link_macos_runtime.py
python3.13 -B tools/verify_macos_network.py --live
python3.13 -B tools/verify_macos_runtime.py
```

在允许公网 UDP 的环境中，再执行：

```sh
python3.13 -B tools/verify_macos_network.py --live --live-quic
```

`--live-quic` 强制公网 HTTP3 请求、不允许 TCP 降级；失败时将诊断保存到报告并返回
非零状态。本地回归是否通过与公网探测是否通过分别记录。

需要显式测试某个路由时，可以从 `native/necko/tests/` 使用辅助解释器运行
`live_quic_probe.py https://目标站点/ --address 公网IP`；证书仍按 URL 主机名验证。

`--live` 可省略；不加时只运行确定性的本地网络回归。

构建器创建 `vendor/necko-derived/` 私有 Python 3.13 环境，按
`config/necko-macos-requirements.txt` 的固定版本和 wheel 哈希安装依赖，再部署动态库
及辅助模块。该目录受 Git 忽略。它是源码开发环境；可迁移 wheel 使用另一套独立 Python 布局，见 wheel 说明。

Mozilla 原生库哈希记录在 `config/necko-macos.lock.json`；Neqo 及 nss-rs 输入由
`config/neqo-macos.lock.json` 和 `native/necko/quic/Cargo.lock` 固定。构建会逐个验证
Neqo/nss-rs 上游文件的 SHA256，Cargo 使用 Firefox vendor 目录离线、锁定构建。
Neqo 源码与原 wheel 保存的上游校验清单一致。

## 使用

```sh
PYTHONPATH=python python3.13 - <<'PY'
from ruyijs import Context

with Context(timeout=25) as ctx:
    ctx.navigate("https://example.com/")
    print(ctx.eval("document.title"))
    print(ctx.eval("performance.getEntriesByType('navigation')[0].nextHopProtocol"))
PY
```

代理继续通过 `Context(proxy="http://127.0.0.1:8080")` 配置；已验证 HTTP 转发及
HTTPS CONNECT，代理设置仅传给对应 Context 的辅助进程。

测试或企业环境需要私有 CA 时，可在创建 Context 前设置 `RUYIJS_CA_BUNDLE` 指向
可信 PEM bundle。该路径会替换默认根证书来源；没有关闭校验的布尔开关。
`RUYIJS_NECKO_PYTHON` 可指定兼容辅助解释器，通常不需要设置。

## 验证证据

21 项网络回归通过（原有 10 项 + 新增 11 项 QUIC），另有原来的 37 项运行时回归通过。
原有 10 项覆盖：

1. HTTP POST 与连接复用。
2. 分块响应、gzip/deflate/Brotli/Zstandard 正文解码。
3. 冲突 Content-Length、非法分块、非法响应头拒绝。
4. 有界超时。
5. NSS HTTPS 正向验证，以及不可信 CA、错误主机名拒绝。
6. 本地 HTTP/2 ALPN 协商与响应。
7. HTTP 代理和 HTTPS CONNECT。
8. 真实 Context 导航、重定向、Cookie、fetch 及页面脚本执行。
9. Context HTTPS/H2 导航与辅助进程清理。
10. 辅助 Python 延迟启动时取消 Context，无残留辅助进程。

新增 QUIC 验证覆盖：

- HTTP3 并发 GET、120 KB POST、CA/主机名拒绝、有界 UDP 超时。
- WebTransport 客户端/服务端发起的双向与单向流、200 KB 数据与 FIN、datagram 回显。
- 子协议协商、发送组/顺序、原生统计、TLS exporter 与服务端导出结果一致。
- 错误证书哈希、HTTP 403 拒绝会话、RESET_STREAM/STOP_SENDING、服务端干净关闭。
- 真实 Context 经 Alt-Svc 升级到 `h3`，导航执行页面脚本后通过 `fetch()` 再次请求。
- JS WebTransport 收发流/datagram/密钥导出/关闭，以及错误哈希同时拒绝 `ready`/`closed`。
- 在已发送 QUIC Initial 的握手中关闭 Context，确认辅助进程退出。

本地服务端是独立进程中的 Neqo 实现，通过系统 UDP socket 收发；它验证真实网络链路，
但客户端与服务端来自同一 Neqo 版本，不能据此声称跨实现互操作已完成。

辅助进程在加载第三方模块前校验 C++ 父进程传入的 PID，并持续监视父进程生命期，
覆盖父进程在 Python 导入阶段已经退出的情况。

| 记录 | 内容 |
| --- | --- |
| `build/macos-arm64/network-build.json` | 原生桥接、Python 输入、依赖和 Mozilla 库哈希 |
| `build/macos-arm64/network-verification.json` | 21 项本地测试、产物身份及可选公网 HTTPS/HTTP3 结果 |
| `build/macos-arm64/logs/network-tests.log` | 本地网络测试日志 |
| `build/macos-arm64/logs/network-live.log` | 外部 HTTPS 验证结果及诊断 |
| `build/macos-arm64/logs/quic-tests.log` | 11 项本地真实 UDP/Context 测试 |
| `build/macos-arm64/logs/quic-live.log` | 可选公网 HTTP3 探测；当前环境拒绝 UDP |
| `build/macos-arm64/runtime-verification.json` | 37 项原有回归及与当前网络构建匹配的状态 |

## 剩余工作

- 公网 HTTP3/WebTransport 与跨实现互操作仍需在允许 UDP 的网络中验证。
- 当前桥接没有启用 QUIC 会话恢复/0-RTT、ECH 或证书压缩；不承诺 Firefox 指纹一致。
- WebTransport 每会话独占连接，池化和拥塞策略偏好仍未单独接入；UDP 不通过 HTTP 代理
  的 CONNECT 隧道。HTTP3 常规请求保持现有代理路由约束及 H1/H2 回退机制。
- 客户端证书认证及完整 Firefox ClientHello/网络指纹一致性未完成。
- HTTP1 桥接尚未完成完整 Gecko 行为对照；当前测试只覆盖上述明确用例。
- 固定根证书包中的旧证书会触发 cryptography 的非正序列号弃用警告。
  当前锁定版本验证通过；升级该依赖前需要重新核对根证书数据，不能忽略为校验成功。
- macOS wheel 和独立 Python/动态库布局已通过本机隔离验证；新机器/VM、正式签名公证、
  较早 macOS 和 Windows 回归仍待处理。
