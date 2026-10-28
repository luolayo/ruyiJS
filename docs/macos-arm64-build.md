# ARM64 SpiderMonkey 构建与接入验证

本文记录第二阶段。第三阶段已生成可执行的产品 `dist/js` 并跑通真实 Python API，
当前状态与运行命令见[运行时说明](macos-arm64-runtime.md)。

## 第二阶段产物

2026-10-27，在本机完成 Firefox 158.0 SpiderMonkey 的原生 ARM64 编译。
`js --version` 返回 `JavaScript-C158.0`，Mach-O 架构为 `arm64`。

此处记录的是上游 shell 和接入编译验证，不能将上游 shell 用作 `RUYIJS_SHELL`。
后续第三阶段已经生成独立的产品 `dist/js`，使用方式见运行时说明。

| 验证 | 实际结果 |
| --- | --- |
| 引擎构建 | ARM64 可执行文件及 `js/src/build/libjs_static.a` 生成成功 |
| 引擎运行 | 7 组检查通过：ARM64、实际进入 Ion、Promise、Wasm、正则/BigInt/Intl、GC、现有值编码器 |
| 上游嵌入 API | `jsapi-tests UTF8` 的 10 项测试通过 |
| 产品接入编译 | shell0、arguments、protocol、environment_schema、environment_snapshot、binding_order、sanitizer_config 共 7 个编译单元通过 |
| WebIDL 数据 | 从 Cocoa browser 配置生成，包含 1008 个接口的成员顺序 |
| 字体数据 | 从同一配置的 `greprefs.js` 生成 250 条字体偏好 |
| 环境基线 | Firefox 158.0 实测 5 组、36 个字段，生成环境头文件 |
| 项目回归 | 24 项测试通过，包含第一阶段通信和新增 UTF-8 参数/文件/trace 路径测试 |

## 固定输入与实际工具链

[spidermonkey.lock.json](../config/spidermonkey.lock.json) 固定官方源码归档 URL、
SHA256、版本及 Git 修订；同时固定用于实测的 Firefox DMG SHA256。

- Mozilla 修订：`3c71aeacdb296402e41fb2084b13e797d1770642`，标签 `FIREFOX_158_0_RELEASE`。
- 源码归档 SHA256：`fc77f7801d7580a600af683cc367e261eb1ec74647e84a91b4a1e3c1dd5aa2bb`。
- 实测工具链：Python 3.13.18、Homebrew Clang/LLD 23.1.4、Rust 1.99.1、cbindgen 0.29.4、macOS SDK 27.0。
- 构建目标：`aarch64-apple-darwin`；配置中记录 `TARGET_CPU=aarch64`、`OS_ARCH=Darwin`。
- 源码输入锁定，工具链完整版本写入构建报告；尚未验证跨机器二进制逐字节相同。
- 编译参数的 deployment target 为 macOS 11.0，但尚未在旧系统验证，不能据此宣布最低支持版本。

本机 Apple 链接器未通过 Firefox 158 的检测，使用 LLVM/LLD 解决，未修改上游
工具链检测代码。原生编译当前有第三方警告，包括已安装 Rust 工具链的
`rust-objcopy` 缺少 `libLLVM.dylib` 的可选处理警告；构建和上述运行检查均通过。

## 重建顺序

从仓库根目录执行。需要 Xcode/SDK、Rust 和以下 Homebrew 工具：

```sh
brew install python@3.13 pkgconf llvm lld
python3.13 -B tools/build_spidermonkey.py prepare
python3.13 -B tools/build_spidermonkey.py bootstrap
python3.13 -B tools/build_spidermonkey.py build --jobs 4
python3.13 -B tools/build_spidermonkey.py commands
python3.13 -B tools/verify_spidermonkey.py
```

源码归档约 777 MiB，解压约 4.6 GiB。所有下载、Mozilla 辅助工具、mach 自建
Python 环境和对象目录均位于被 Git 忽略的 `build/`。
`bootstrap` 使用 `--no-system-changes`，不安装另一套系统 clang/rust；其余辅助工具
放在 `build/mozilla-state/`。LLVM 和 LLD 的自定义安装位置可通过 `--llvm`、`--lld` 指定。

生成 browser 数据只需配置及 export/misc 目标，不需要编译完整 Firefox：

```sh
python3.13 -B tools/generate_browser_inputs.py configure
python3.13 -B tools/generate_browser_inputs.py export --jobs 2
python3.13 -B tools/generate_browser_inputs.py generate
python3.13 -B tools/prepare_firefox_reference.py
python3.13 -B tools/capture_firefox_baseline.py
python3.13 -B tools/check_spidermonkey_integration.py
```

独立 browser 配置关闭 Wasm 沙箱库选项，以免表生成要求额外的 WASI SDK。
WebIDL 文件和字体偏好仍来自真实的 macOS Cocoa 构建配置。

参考 Firefox 仅解压至 `build/reference/Firefox.app`，不替换系统应用。
采集使用独立的临时 profile，结束后清理。实测的 `navigator.webdriver=true`
被原样保留；这份无头自动化环境仅作为开发基线，`publishable_default_profile=false`。
不将其当成普通用户浏览器指纹，也不把它写入已发布的 Windows 默认配置。

项目测试从 Python 目录运行：

```sh
cd python
python3.13 -B -m unittest discover -s tests -v
```

## 产物与证据

| 路径 | 内容 |
| --- | --- |
| `build/spidermonkey-arm64/dist/bin/js` | 本机编译的上游 shell，仅用于开发验证 |
| `build/spidermonkey-arm64/js/src/build/libjs_static.a` | 后续产品链接需要的引擎静态库及其对象树 |
| `build/spidermonkey-arm64/compile_commands.json` | 从实际构建导出的编译参数 |
| `build/macos-arm64/engine-build.json` | 源码、工具链、目标、可执行文件哈希 |
| `build/macos-arm64/engine-verification.json` | 引擎/值编码器运行结果及上游 UTF-8 测试结果 |
| `build/macos-arm64/browser-inputs.json` | WebIDL、字体、Sanitizer 输入和输出哈希 |
| `build/macos-arm64/environment-baseline.json` | 参考版本、实测基线、生成头文件和采集限制 |
| `build/macos-arm64/generated/` | shell 集成源码、协议资源及四类生成头文件 |
| `build/macos-arm64/integration.json` | 7 个编译单元的命令、输入/输出哈希和剩余依赖 |
| `build/macos-arm64/logs/` | 每次构建/接入编译日志及命令记录 |

当前 shell SHA256 为 `74b133ccc597b7b03060941b62c4fd7b74660f7be7fc7f5ffa2d282ffc1cfee7`。
构建产物不加入 Git。

## 产品链接边界

已生成的 shell 对象调用原有 `ruyijs::Run`、`RunWorker` 和异常捕获入口，完整
链接必须接回这些生产实现。没有提供假的入口或用普通 JS shell 冒充产品。

第二阶段识别了以下依赖；当前落实状态见运行时说明：

1. Worker 生命周期、网络辅助进程、随机数/加密、字体和图片的平台后端。
2. `vendor/compression-native`、`vendor/image-native` 的源码清单，以及
   `vendor/urlpattern-native` 的自定义 Rust FFI。
3. Necko 的自定义原生桥接和已知可从发布 wheel 恢复的 Python 辅助代码。
4. 正式产品链接入口与最小 `Context.eval()` 端到端验收。

`integration.json` 列出 23 个包含 Windows SDK 头文件的生产目录文件，供逐项检查。
其中也包含已经使用条件编译适配的通信文件，这个数字不等于尚未解决的阻塞数量。
`setup.py` 仍只发布 Windows wheel；Windows 原生回归和 macOS 发布验收留待后续阶段。
