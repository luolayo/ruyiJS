# macOS ARM64 CI

工作流：`.github/workflows/macos-arm64-wheel.yml`。
触发方式为移植分支/main 的代码推送、相关 pull request，以及手动 `workflow_dispatch`。

## 两个独立 GitHub VM

- **build**：在 `xcode-27` ARM64 runner 上检查系统/SDK/固定 OpenSSL，构建 Firefox 158
  SpiderMonkey、平台生成表、全部产品 C++、Rust URLPattern、NSS/Neqo 桥接，运行原有
  运行时/网络回归，最后生成包含 Python 和动态库的 wheel。
- **install**：在另一个 `xcode-27` VM 上重新检出同一提交，仅下载 wheel、QUIC 测试
  服务端和哈希清单。拒绝已有 `dist/js`、开发 venv、SpiderMonkey 对象树或 wheel-runtime
  目录的 checkout；不恢复构建缓存、不编译产品、不借用第一个 VM 的辅助 Python。

`xcode-27` 是 GitHub 当前公布的 macOS 27 ARM64 **preview** 镜像标签；`macos-latest`
仍指向 macOS 26，不能用于最低 macOS 27 的 wheel。
参考：[官方 runner 镜像清单](https://github.com/actions/runner-images/blob/main/README.md)、
[该镜像的软件/系统版本](https://github.com/actions/runner-images/blob/main/images/macos/xcode-27-arm64-Readme.md)。

工作流只缓存经过 SHA256 校验的下载归档，不缓存源码解压目录、对象文件或运行时。
构建并发设为 2，以适应标准 ARM64 runner 的内存。Actions 固定到完整提交 SHA，
GITHUB_TOKEN 仅有 contents:read，不发布 PyPI 包，也不需要签名密钥。

## 安装验证

`tools/verify_macos_wheel.py --artifact-dir artifacts/macos-arm64 --require-clean-checkout`
验证产物 SHA256 及构建/安装 checkout 提交相同。在临时目录使用固定的 Python 3.14：

1. 禁网执行 pip 离线安装；使用正常的 bytecode 编译行为。
2. 客户端及其子进程禁止读取仓库、Homebrew 和 `/usr/local`。
3. 使用 wheel 中的私有 Python 3.13 启动网络辅助进程。
4. 运行 17 项已安装产品测试及搬迁目录后的 5 项网络测试，并验证卸载清理。

本地网络服务端使用单独复制的包内解释器/依赖和构建 job 产出的 Neqo peer。
只有生成测试证书库的 NSS 命令行工具由测试 VM 的 Homebrew 提供；客户端始终无法访问它。

报告记录 GitHub run/job/attempt、提交、镜像版本、系统及 CPU 架构。只有同时满足
GitHub-hosted 环境、仅使用产物、干净 checkout 检查时，才标记 `new_machine_or_vm_tested=true`；
本地运行这些脚本不会被记为新 VM 验收。公网 QUIC 仍是单独的验收项，不作为这些本地网络测试的结果。

## 产物与复现

每次运行保留 14 天的三个 Actions artifact：

- `macos-arm64-installation-inputs`：wheel、Neqo 测试服务端、wheel 构建报告、提交/哈希清单。
- `macos-arm64-build-evidence`：源码/工具链/构建/网络/运行时报告及编译日志，失败时也上传。
- `macos-arm64-installation-evidence`：新 VM 的 wheel 验证报告、安装、测试、搬迁及卸载日志。

在有相同前置工具的 ARM64 Mac 上，可按顺序执行：

```sh
python3.13 -B tools/ci_macos.py preflight
python3.13 -B tools/ci_macos.py engine
python3.13 -B tools/ci_macos.py inputs
python3.13 -B tools/ci_macos.py product
python3.13 -B tools/ci_macos.py verify
python3.13 -B tools/ci_macos.py wheel
python3.13 -B tools/ci_macos.py export
```

安装阶段必须在另外的干净 checkout 执行，且 checkout 提交与 `ci-artifact.json` 一致。
不要通过复制 build/ 或 vendor/ 来掩盖安装阶段缺失依赖的问题。

截至配置提交时，远端运行尚未完成；以 Actions 运行及其验证报告为最终证据。
