# macOS ARM64 移植计划

## 目标与基线

- 基线：`989848c`，开发分支：`macos-arm64`。
- 目标：M 系列 Mac 上的原生 ARM64 ruyiJS，保留 Python 3.10+ API 和每个 Context
  独立进程的隔离方式。
- Windows x64 仍是已发布平台；macOS 在完整验收前标为实验性。
- 保留 SpiderMonkey 和现有 C++ Web API 实现。平台差异放到进程、通信、加密、
  字体、图片和网络适配层中。
- 最低 macOS 版本在引擎、动态库和打包验证后确定；不能只按当前开发机推断。

## 分阶段交付与验收

| 阶段 | 工作 | 验收条件 | 状态 |
| --- | --- | --- | --- |
| 1. 平台通信 | Python 平台分派、Unix socket、Context 进程启动、C++ 同步/异步 Pipe | 真正的 Python ↔ ARM64 C++ 子进程互通；帧边界、队列上限、超时、断连和资源清理通过测试 | 已实现，验证结果见下文 |
| 2. 引擎构建 | 锁定 Mozilla 源码、记录工具链；恢复必要生成器；建立 ARM64 编译入口；生成字体、WebIDL、Sanitizer 和实验环境基线表 | ARM64 SpiderMonkey 可按记录重建，shell 集成点编译通过，剩余产品链接依赖有明确清单 | 已完成本机构建与接入编译验证，见[构建说明](macos-arm64-build.md) |
| 3. 产品运行时 | 移植参数/路径、Worker 进程、加密、字体、图像、Necko 辅助进程；补齐缺失的原生桥接 | 真实 `Context.eval()`、DOM、回调、事件循环、网络、Worker、WebCrypto 和 Canvas 回归通过 | 已跑通真实 `Context.eval()`、HTTP/HTTPS（H1/H2/H3）和 WebTransport；H3/WebTransport 已通过本地真实 UDP 及 Context 验证，公网 UDP 请求被当前环境拒绝 |
| 4. 交付 | 按平台选择 runtime 清单、动态库路径/签名、ARM64 wheel、Mac/Windows 持续集成 | 干净 Mac 离线安装后可运行；Windows 构建回归通过；发布物和依赖清单可核验 | 本地 ARM64 wheel 已打包；离线安装、拒绝访问仓库/Homebrew 的沙箱测试及搬迁验证通过；新机器/VM、正式签名公证和 Windows CI 待完成 |

每阶段提交可复核的源码与运行证据。阶段 1 的通信测试程序不提供 JavaScript
解释能力，不能用它的成功宣称 `Context.eval()` 已在 Mac 上运行。

## 第一阶段实现边界

Python 的 `_pipe.py` 选择平台后端：Windows 命名管道实现原样移至
`_pipe_windows.py`，macOS 使用 `_pipe_posix.py`。Mac 端在 `/tmp` 下创建权限
为 0700 的私有目录，避免 macOS 默认临时路径超过 Unix socket 路径长度限制。

C++ 沿用 `runtime/Pipe` 和原有帧解析、异步读写、队列限制；新增
`pipe_posix.cpp`、`pipe_posix_async.cpp` 负责 Unix socket 系统调用。
Windows 分支继续使用原有 OVERLAPPED 实现。

通信契约保持不变：4 字节小端长度、UTF-8 JSON/任意帧字节、最大 16 MiB，
异步队列上限为 256 帧和 16 MiB + 4 字节。Mac 与 Windows x64 均为小端平台。
同步 C++ 端的阻塞生命周期仍由 Python Context 的请求期限和子进程终止控制。
Worker 的非阻塞 Pipe 已适配，但 Worker 的进程启动还没有移植。

`Context` 在 Mac 上不传 Windows 创建标志，查找 `dist/js`，并保留 POSIX
启动异常。缺少运行时时明确报告实验性原生构建尚未安装。
`setup.py` 和发布平台声明暂时保持 Windows-only，避免产生不能运行的 Mac wheel。

运行第一阶段检查（需要 Xcode Command Line Tools）：

```sh
cd python
python3 -B -m unittest discover -s tests -v
```

测试使用 Python 标准库，并在临时目录编译真实生产 `pipe*.cpp`；无需 venv 或
第三方测试框架，构建产物随测试清理。测试覆盖两个连接方向、同步/异步收发、
分片与合并帧、16 MiB 帧、非法长度、背压/超时、连接隔离、队列边界、
断连时 SIGPIPE、启动失败及正常关闭。Context 生命周期测试使用明确标注的
通信测试程序，未加载 SpiderMonkey。

## 构建材料如何补齐

原版存在两条不同的链路：`tools/build.py` 使用外部 SpiderMonkey 构建目录，
而 `setup.py` 将预编译的 Windows runtime 装入 wheel。
缺少项目级 CMakeLists.txt 并不表示原构建入口不存在。

- 构建脚本曾在 `dcd9645` 删除；阶段 2 已从父提交
  `d33062f42685c9c03f46b5b23cf5c03479d06390` 恢复实际需要的生成器与源码清单。
- `generate.py` 保存 shell 集成方式，不必猜测缺失的入口补丁。
- 原构建器写死了 Windows donor、`clang-cl.exe`、`.obj/.lib` 和 Rust Windows target。
  现已增加独立的 ARM64 产品编译与链接入口，重新生成所有对象文件。
- 字体/WebIDL/Sanitizer 表已由锁定的 Firefox 158.0 源码生成。环境基线已从隔离的
  Firefox 158.0 实测生成，保留自动化状态，尚不作为发布默认指纹。
- Mac 压缩后端使用固定 Mozilla 源码中的 Brotli 及 zlib 接口，图像改接 ImageIO；
  不再要求 Windows 专用的 WIC/AVIF 构建目录。完整像素一致性仍待验证。
- URLPattern 的既有 C ABI 已在 `native/urlpattern/` 重建，并纳入引擎的同一 Rust 库。
- 正式 Windows wheel 的清单能恢复 58 个项目 Necko Python 扩展源码；基础
  `necko` Python 包也在 wheel 中。之前已验证过这条恢复路径，本阶段不重新引入
  尚未使用的源码和 Windows 运行时缓存。
- `necko_core`、`necko_quic` 未找到完整原桥接源码。已根据 Python ABI 重建 ARM64
  socket/HTTP1/NSS 和 Neqo 0.31.1 桥接，接通 H1/H2/H3 与 WebTransport，见[网络说明](macos-arm64-network.md)。

## 验证状态

开发机为 macOS ARM64，Apple Clang 21。第一阶段已使用
`-std=c++17 -Wall -Wextra -Werror` 编译 7 个生产通信单元，21 项测试全部通过。
第二阶段已构建并运行原生 ARM64 SpiderMonkey 158.0，7 组引擎检查、10 项上游
UTF-8 JSAPI 测试通过；7 个产品接入相关编译单元通过；项目回归增至 24 项并全部通过。
第三阶段已完成完整产品链接和真实 Python API 验证，详情见[运行时说明](macos-arm64-runtime.md)。
HTTP/HTTPS（H1/H2）已通过本地及外部验证；HTTP/3 和 WebTransport 已通过本地真实 UDP 与
Context 验证。公网 QUIC 当前被网络环境拒绝，完整 Firefox 指纹一致性、Windows 原生回归
及发布签名仍待完成。

参考：

- [Mozilla 支持的构建目标](https://firefox-source-docs.mozilla.org/build/buildsystem/supported-configurations.html)
- [SpiderMonkey 构建说明](https://firefox-source-docs.mozilla.org/js/build.html)
- [Mozilla macOS 构建说明](https://firefox-source-docs.mozilla.org/setup/macos_build.html)
