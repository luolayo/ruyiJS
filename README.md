<div align="center">

# 🦊 ruyiJS

### Run any site's JavaScript from Python — with the real Firefox engine.

**A new-generation, minimalist browser purpose-built for AI-driven automation.**<br>
The authentic Firefox JavaScript engine and networking stack, with no window and no renderer —<br>
made for web scraping, JS reverse engineering, data collection, and getting past bot checks.

[![PyPI](https://img.shields.io/pypi/v/ruyijs?label=pypi&color=111111&logo=pypi&logoColor=white)](https://pypi.org/project/ruyijs/) [![Python](https://img.shields.io/badge/Python-%E2%89%A53.10-111111?logo=python&logoColor=white)](https://pypi.org/project/ruyijs/) [![License](https://img.shields.io/badge/license-MPL--2.0-111111)](LICENSE) [![Windows](https://img.shields.io/badge/Windows%20x64-0078D4?logo=windows&logoColor=white)](https://pypi.org/project/ruyijs/) [![LinuxDO](https://img.shields.io/badge/LinuxDO-community-FFB003?logo=discourse&logoColor=white)](https://linux.do/t/topic/3078486)

<sub>Sponsored by</sub>

<a href="https://www.fastaitoken.com"><img src="assets/sponsor-fastaitoken.png" height="42" alt="FastAIToken"></a>

**[Install](#-installation)** &nbsp;·&nbsp; **[Features](#-features)** &nbsp;·&nbsp; **[Verification systems](#-verification-systems-it-defeats)** &nbsp;·&nbsp; **[Examples](#-examples)** &nbsp;·&nbsp; **[FAQ](#-faq--troubleshooting)** &nbsp;·&nbsp; **[Contact](#-contact)** &nbsp;·&nbsp; **[LinuxDO](https://linux.do/t/topic/3078486)** &nbsp;·&nbsp; **English** · [简体中文](README.zh-CN.md)

<br>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/architecture-dark.svg">
  <img src="assets/architecture.svg" width="880" alt="ruyiJS architecture: your Python code drives a ruyiJS Context — an isolated process holding the SpiderMonkey JS engine, 38 browser contexts, and the Necko network stack — which talks to the target site.">
</picture>

</div>

<br>

## Is ruyiJS for you?

Headless Chrome and Playwright hand you a whole browser: a GPU-rendering, window-managing, memory-hungry process that anti-bot vendors have spent years learning to detect. ruyiJS takes the opposite path — it embeds only the Firefox internals that matter for automation and leaves the rest behind:

- **The real engine, not an impersonation.** Genuine SpiderMonkey (Firefox 158) and the Necko network stack execute a site's JavaScript, challenges, signatures, and fingerprints exactly as Firefox would.
- **Truly headless.** No window, no layout, no renderer. A pure JavaScript + Web API environment that starts fast and stays light.
- **Isolated and reproducible.** Each `Context` is its own process with a persistent JavaScript world and its own proxy, so sessions never leak into each other.
- **Offline when you need it.** Serve scripts and responses yourself and replay a whole captured flow with no network.

If you scrape, reverse-engineer web JavaScript, or collect data behind a challenge, it's for you. If a plain HTTP client already gets your pages, you don't need it.

Runs on **Windows x64** with **Python 3.10+** (verified on Python 3.14). The wheel bundles the pinned native runtime, so there's nothing else to download.

## 📦 Installation

```sh
python -m pip install ruyijs
```

**Requirements:** Python 3.10+ on Windows x64 (64-bit). Verified on Python 3.10 – 3.14.

The wheel ships the SHA256-pinned SpiderMonkey + Necko runtime (~42 MB). Local scripts run offline right after install — no browser download, no external dependencies.

To upgrade:
```sh
python -m pip install --upgrade ruyijs
```

To verify the installation:
```python
import ruyijs
print(ruyijs.__version__)   # 0.1.6
```

## 🚀 Quick start

**1 · Open a context and run JavaScript.** Variables and functions persist across `eval` calls within the same context.

```python
from ruyijs import Context

with Context() as context:
    context.eval("let count = 40")
    print(context.eval("count += 2"))        # 42
    print(context.eval("navigator.userAgent"))
```

**3 · Point it at a real target.** Configure the environment, load the page, and let the site's own JavaScript mint whatever token it demands.

```python
with Context(proxy="http://127.0.0.1:7890") as context:
    context.configure_fingerprint({
        "navigator": {"language": "zh-CN", "hardwareConcurrency": 8},
        "locale": {"timezone": "Asia/Shanghai"},
    })
    context.load_page("https://target.example/", html)
    token = context.eval("window.__sign(payload)")   # run the page's signer
    print(token)
```

## 🏗️ How it fits together

```
Python  ──►  ruyiJS Context (isolated process)  ──►  Target site
                 ├─ SpiderMonkey — Firefox 158 JS engine
                 ├─ 38 browser contexts — DOM · Canvas · Workers · iframes · …
                 └─ Necko — HTTP/1.1 · 2 · 3, per-context proxy
```

Your Python code drives a `Context`. Inside it, the genuine SpiderMonkey engine runs the page's scripts against a real DOM and 38 bounded browser subsystems, while in-page `fetch`/XHR ride the Necko transport. The implementation lives under [`src/`](src) (domain, application, and every browser subsystem) and [`python/ruyijs/`](python/ruyijs) (the binding).

## ✨ Features

### Run a site's JavaScript

Execute scripts in a persistent context, load real HTML with iframes and classic scripts, and query the resulting DOM. References to live JS objects come back as `JSObject` / `JSFunction` you can call from Python.

| Capability | How |
| :-- | :-- |
| Execute JS, keep state | `context.eval(src)` — variables and functions persist |
| Get a callable back | `context.eval(src, to_py=False)` → `JSFunction` |
| Load a page | `context.load_page(url, html)` — relative URLs resolve against `url` |
| Top-level navigation | `context.navigate(url)` — no Referer, `Sec-Fetch-Site: none` |
| Query the DOM | `context.eval("document.querySelector('#x').textContent")` |

```python
with Context() as context:
    context.set("config", {"offset": 2})
    add = context.eval("(value) => value + config.offset", to_py=False)
    print(add(40))  # 42
```

### Configure the browser environment

Set Navigator, Screen, viewport, timezone, and locale through one validated profile surface. Commit it before the first page script runs.

```python
with Context() as context:
    context.configure_fingerprint({
        "navigator": {"language": "zh-CN", "hardwareConcurrency": 8},
        "screen": {"width": 1920, "height": 1080},
        "viewport": {"width": 1280, "height": 720},
        "locale": {"timezone": "Asia/Shanghai"},
    })
    print(context.eval("[navigator.language, screen.width]"))  # ['zh-CN', 1920]
```

### Native network over Necko

In-page `fetch` and XHR ride real HTTP/1.1, 2, and 3, through a proxy scoped to the context. Serve responses yourself with `put_resource()` to replay an entire captured flow offline. Inspect every request with `net_log()`.

```python
with Context(proxy="http://127.0.0.1:7890", timeout=30) as context:
    context.load_page("https://example.com/", "")
    context.eval("globalThis.r = null; fetch('/api').then(x => x.json()).then(v => r = v)")
    context.advance(25)               # drive the event loop until it settles
    print(context.eval("r"))
```

### Python ↔ JavaScript bridge

Pass data in with `set()`, get callable JS functions out, and expose Python functions to the running script. Workers, Service Workers, and iframes are included.

```python
with Context() as context:
    context.expose(lambda a, b: a + b, "add")
    print(context.eval("add(20, 22)"))  # 42
```

### Deterministic clock

Drive timers with a logical clock for perfectly reproducible runs, or use the system clock for live work. The host advances time explicitly.

```python
with Context() as context:
    context.configure_clock("logical", epoch_ms=1700000000000)
    context.eval("globalThis.result = 0; setTimeout(() => { result = 42 }, 10)")
    context.advance(10)
    print(context.eval("result"))  # 42
```

### Errors and logs

JavaScript exceptions surface as `JSError` with name, message, and stack. `console_log()` and `net_log()` return the captured console and network records.

```python
from ruyijs import Context, JSError

with Context(timeout=10) as context:
    try:
        context.eval("throw new TypeError('bad input')", filename="demo.js")
    except JSError as error:
        print(error.name, error.message)  # TypeError bad input
        print(error.stack)
```

## 🛡️ Verification systems it defeats

Each example drives the site's own JavaScript to produce the parameters it demands, then completes the flow end to end. All ship runnable in the package: `python -m ruyijs.examples <name>`.

| System | Category | Example |
| :-- | :-- | :-- |
| **瑞数 Ruishu 5/6** | Dynamic VM / page protection | `fangdi` · `cebwm` |
| **极验 Geetest** | Slider / one-click | `geetest` |
| **腾讯天御 Tencent Captcha** | No-feel + slider | `tianyu` |
| **数美 Shumei** | Slider | `shumei` |
| **网易易盾 NetEase Yidun** | Smart check | `yidun` |
| **Arkose Labs + iovation** | Enterprise risk / device | `expedia-taap` |
| **Akamai Bot Manager 3.x** | sensor_data + sbsd challenge | `akamai` |
| **阿里 234 / fireyejs** | JSVMP bytecode VM / bx-ua token | `ali234` |
| **CreepJS** | Fingerprint audit — passes every section | `creepjs` |

Full production data-collection flows: **BOSS 直聘**, **今日头条 Toutiao**, **抖音 Douyin**, **小红书 RedNote**, **Google**, **Expedia TAAP**.

> 🔒 **Strictly prohibited for any unlawful use.** ruyiJS is provided **solely for research into a new generation of AI browsers.** Live results depend on current network conditions and each site's present responses.

## 🧪 Examples

Examples ship inside the package — no need to clone the repo:

```sh
python -m ruyijs.examples                      # list every example and its install path
python -m ruyijs.examples google --query python --pages 1
python -m ruyijs.examples boss --query ai --city 101210100
python -m ruyijs.examples fangdi               # 网上房地产 (Ruishu 6)
python -m ruyijs.examples cebwm --pages 3      # 光大理财 (custom Ruishu)
python -m ruyijs.examples toutiao --pages 3    # 今日头条
python -m ruyijs.examples xhs --pages 3        # 小红书 / RedNote home feed
python -m ruyijs.examples geetest              # 极验 one-click
python -m ruyijs.examples yidun                # 网易易盾
python -m ruyijs.examples shumei               # 数美 slider
python -m ruyijs.examples tianyu               # 腾讯天御
python -m ruyijs.examples akamai              # Akamai Bot Manager 3.x
python -m ruyijs.examples ali234              # 阿里 234 / 淘宝 bx-ua
```

Every example supports `--direct` (direct connection) and `--proxy http://127.0.0.1:7890`. Add `--help` after a name for all options, and `--output result.json` to save results. Each example directory ships its own README.

## 📚 Documentation & API

| | |
| :-- | :-- |
| **`Context.eval` / `set` / `expose`** | Execute JS, pass data in, expose Python callbacks |
| **`load_page` / `navigate` / `put_resource`** | Load HTML, top-level navigation, serve resources offline |
| **`configure_fingerprint` / `configure_environment`** | Navigator, Screen, viewport, timezone, locale |
| **`configure_clock` / `advance` / `tick`** | Logical vs. system clock, drive the event loop |
| **`JSError` / `console_log` / `net_log`** | Errors as exceptions, console and network records |
| **`JSObject` / `JSFunction` / `get_runtime_path`** | Live JS handles, bundled-runtime path |

## 📏 Scope & limitations

ruyiJS provides JavaScript execution and a broad Web API environment on **Windows x64**. It has **no browser window and no full page layout or rendering** — it is a tool for automation, analysis, and research. Use it in compliance with the terms of service of any site you interact with and with applicable law.

**Related:** [**ruyiHttp**](https://gitee.com/losenine888/ruyiHttp) — a Requests-style Python HTTP library built on Firefox's native networking components.

## ❓ FAQ / Troubleshooting

<details>
<summary><b>What Python versions are supported?</b></summary>

Python 3.10 and above on Windows x64 (64-bit). Tested up to Python 3.14.
</details>

<details>
<summary><b>Does it work on macOS or Linux?</b></summary>

Published wheels are still Windows x64 only. A local experimental Apple Silicon wheel and source build now run the real `Context.eval()`, DOM, callbacks and HTTP/HTTPS networking (HTTP/1.1, HTTP/2 and HTTP/3) plus WebTransport on macOS 27. See the [macOS runtime guide](docs/macos-arm64-runtime.md) and [network guide](docs/macos-arm64-network.md). HTTP/3 and WebTransport are verified against real local QUIC peers; public HTTP3 probes currently fail with UDP connection-refused errors in the test environment. The [macOS wheel guide](docs/macos-arm64-wheel.md) covers offline installation and isolated tests; this wheel has not been published or notarized. Linux is not supported yet.
</details>

<details>
<summary><b>Do I need to download a browser?</b></summary>

No. The wheel bundles the pinned SpiderMonkey + Necko runtime. Everything works offline right after `pip install ruyijs`.
</details>

<details>
<summary><b>Context hangs or doesn't respond</b></summary>

- Make sure you use the `with` statement (`with Context() as ctx:`) so the process is cleaned up properly.
- If using a proxy, verify it is reachable: `context = Context(proxy="http://127.0.0.1:7890")`.
- Increase the timeout: `Context(timeout=60)`.
- On Wine, upgrade to ≥ 0.1.5 which fixes a known navigate deadlock ([issue #1](https://github.com/martinkeith700/ruyiJS/issues/1)).
</details>

<details>
<summary><b>JSError: script error</b></summary>

The site's JavaScript threw an exception. Inspect `error.name`, `error.message`, and `error.stack` to locate the cause. If the page relies on APIs not yet implemented, the stack trace will point to the missing call.
</details>

<details>
<summary><b>How do I use a proxy?</b></summary>

```python
with Context(proxy="http://127.0.0.1:7890") as ctx:
    ctx.navigate("https://example.com/")
```

HTTP, HTTPS, and SOCKS5 proxies are supported per-context.
</details>

<details>
<summary><b>How do I run examples?</b></summary>

```sh
python -m ruyijs.examples              # list all examples
python -m ruyijs.examples google --query python
python -m ruyijs.examples akamai --proxy http://127.0.0.1:7890
```
</details>

## 💬 Contact

Questions, permission requests, commercial licensing, or just to talk shop — add the author on WeChat, or scan to join the discussion group.

<table>
<tr>
<td align="center"><img src="assets/wechat-qr.jpg" alt="WeChat QR — 如意" width="220"><br><b>WeChat:</b> 如意</td>
<td align="center"><img src="assets/wechat-group-qr.jpg" alt="Group — AI 浏览器过检测交流群" width="220"><br><b>Group:</b> AI 浏览器过检测交流群</td>
</tr>
</table>

> The group QR refreshes periodically; if it has expired, add the author on WeChat (如意) for an invite.

## 📄 License

Licensed under the **[Mozilla Public License 2.0](LICENSE)**. See [`NOTICE`](NOTICE) for third-party attributions.

> 📌 As a courtesy: for **redistribution and commercial use, please obtain the author's permission** — add the author on WeChat (ID: **如意**) or open an issue on [GitHub](https://github.com/martinkeith700/ruyiJS).

If ruyiJS saved you from reimplementing a browser, a ⭐ helps others find it.
