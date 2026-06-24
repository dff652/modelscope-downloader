# ModelScope Downloader —— 开发新会话起点（START HERE）

> 接手「这个独立 Win10 工具（双击 exe 下 ModelScope 模型，给 air-gapped 部署传模型用）」的开发会话，**先读这页**。
> 2026-06-24 起。独立项目（`/home/ym/modelscope-downloader/`，已 `git init`），**从 ts-platform 的 `scripts/tools/modelscope-download/`（CLI 版）拆出独立化**，目标是给**非技术操作员**的双击 GUI exe。

## 一句话背景

worker08（910C，air-gapped）等机器没外网，模型得在联网机下好再传。给会跑命令的人 CLI 就够；给**不会命令行的操作员**要**双击即用的 GUI exe**。故独立成项目 + GUI + pyinstaller 打包。

## 结构

```
modelscope-downloader/
├── app.py              核心 download() + CLI(argparse) + GUI(tkinter) 三合一; 无参数→GUI, 带参数→CLI
├── build.bat           Windows 上 pyinstaller --onefile --windowed --collect-all modelscope 出 exe
├── requirements.txt    modelscope (+构建时 pyinstaller)
├── README.md           操作员/打包者/CLI 用法
├── START-HERE.md       本文（开发起点）
└── .gitignore          build/ dist/ *.spec models/ 等
```

## 现状（已完成）

- ✅ **`app.py` 写好**：`download()` 引擎（`snapshot_download` + 断点续传 + 重试 + `max_workers` 探测）；CLI（argparse）；GUI（tkinter：模型 id 下拉/粘贴、文件夹浏览、下载、日志框、`dir_size` 轮询当进度、完成/失败弹窗、worker 线程 + `queue`→`root.after` 线程安全刷新）。
- ✅ **dev box 语法验过**（`ast.parse` / `python -m py_compile`）。
- ✅ **核心下载逻辑已实证**：同款 `snapshot_download` 封装在 ts-platform 侧实际下成了 `Qwen/Qwen3-0.6B`、`Qwen/Qwen3.5-0.8B`（modelscope.cn 可达、续传可用）。
- ✅ `build.bat` 写好（含 `--collect-all modelscope` 应对动态导入；自动认 `icon.ico`；失败时打印逐步补 hidden-import 的提示）。

### 2026-06-24 第二会话（v0.2.0，本机 Linux 可验的都验了）

- ✅ **一键打包**：新增 `make_archive()` → 下完生成 `<模型>.tar` + `<模型>.tar.sha256`（边写边算 sha256，不回读；流式 `tarfile mode="w|"`）。**操作员全程不用开终端**（这是产品目标，旧版让操作员手敲 `tar` 是自相矛盾的缺口，已补）。
  - CLI：`--tar`；GUI：下完弹「现在打包吗？」→「是」就在 worker 线程里打包，完成再弹窗给 `.tar` 路径。
  - **已在 Linux 实测**：`make_archive` 造一个假模型目录 → 打 tar → `sha256sum -c` 报「成功」→ `tar -xf` 解出与原目录 `diff -r` 全等。流式 sha256 与落盘字节一致（`sha256sum -c` 通过即证）。
- ✅ **跳过演示文件**：`--skip-media` / GUI 勾选框 → `MEDIA_EXCLUDE`（图片/视频/音频 glob）当 `ignore_patterns`，更快更省盘。
- ✅ **减小 pyinstaller 动态导入面**：`download()` 改为先 `from modelscope.hub.snapshot_download import snapshot_download`（绕开顶层 LazyImportModule），失败兜底顶层。意在缓解 #1 构建风险——但**仍未在真 Windows 上验**。
- ✅ GUI 用 mock tkinter 跑过 `run_gui()` 构造全程无 `NameError`（无显示环境的最大限度验证；事件回调体仍未在真机触发）。
- ✅ **`build.bat` 大改（起因：真机上只报 `[x] pip install failed` 不给细节）**。用工作流「调研+起草+3 路对抗审查 cmd.exe 正确性」产出，已应用 2 处审查修复：
  - **全程 tee 到 `build.log`**（纯 cmd，不用 PowerShell 避免 `$LASTEXITCODE` 被吞）；失败时 `type` 全日志到屏幕 + 给路径。
  - **pip 装依赖：默认 PyPI → 失败自动换清华镜像重试**（`-i ... --trusted-host ... --default-timeout 120 --retries 5`）；两次都败给镜像/代理/SSL/磁盘的可复制排错命令。
  - 开头打印环境（where python / 版本 / pip 版本 / 位数）并 **真正拦截 32 位 Python**（`for /f` 取 `sys.maxsize` 探针，避开 for/f 里单引号坑）。
  - `pyinstaller` 改 `python -m PyInstaller`（`--user` 装也能找到）；构建后查 exe 是否被杀软误删。
  - **关键调研结论**：`pip install modelscope`（不加 `[framework]/[all]` 等 extra）本就是 hub-only 轻量包（几 MB 纯 Python，**不拉 torch**），正是 `snapshot_download` 所需——别加 extra，否则会拉 GB 级 + 需 MSVC 编译。
  - **已在真 Windows 首跑一次**（`D:\ts-plat\modelscope\`）：环境关卡正常工作，逮到真机的 **微软商店 `python.exe` 别名占位**坑（`...\WindowsApps\python.exe`，非真 Python，`--version` 无输出）。初版把空输出**误报成「32 位」**，已修：现在 `for /f` 取 `python --version`，无输出→明确报「商店占位/没装 Python」并给「装 64 位 python.org + 关应用执行别名 + 开新窗口重跑」三步；位数关卡只在真有版本号时才判。**还没跑到 pip/打包那步**（卡在没真 Python）。
  - 存盘须 UTF-8 无 BOM（已确保；BOM 会毁第 1 行）。下一真机步骤：装好 64 位 Python 后重下 `dist/` 里的 zip 再跑。

## ⚠️ 未做 / 未测（**关键，下个会话先干这些**）

1. **GUI 没在真 Windows 上跑过**：tkinter 行为、文件夹选择、弹窗、线程刷新都只在逻辑上正确，**待真机验证**（dev box 是 Linux 无显示，跑不了 GUI）。
2. **exe 没在 Windows 构建/测过**：`pyinstaller --collect-all modelscope` 多半还**缺 hidden-imports**（modelscope 动态 import 多），首次构建大概率要补 `--hidden-import` 或 `--collect-submodules`；exe 体积会很大（modelscope 依赖重）。**这是最大未知**。
3. 进度是 `dir_size` 轮询（**粗略**），不是真百分比；tqdm 在 `--windowed` 无 console 不显示（故才用轮询）。可改成解析 modelscope 回调/总大小。
4. **无图标文件**（build.bat 已会自动认 `icon.ico`，但还没有这个文件）/ 无签名（Windows SmartScreen 可能拦未签名 exe，要让操作员「仍要运行」）。
5. 无自动更新 / 版本检查；无 LICENSE。
6. **打包大模型的磁盘/耗时未在真机量过**：300G 打 tar 要再占 ~300G 且耗时数分钟，GUI 里只 log「打包中…」没真进度条。

## 下一步（开发待办，按优先级）

1. **在一台真 Windows 上跑 `build.bat`** → 修 pyinstaller 缺的 hidden-imports（看 exe 运行时报的 `ModuleNotFoundError` 逐个补），直到双击能开 GUI + 下成一个小模型 + **走一遍下完「打包成 .tar」**。把可用的 pyinstaller flags/`.spec` 固化回 `build.bat`。← **唯一的真机阻塞项，本机 Linux 做不了**。
2. ~~加「下载完自动打 tar + 出 sha256」~~ ✅ 已做（`--tar` / GUI 弹问，已 Linux 实测）。~~`--include` 预设跳 video/preprocessor~~ ✅ 已做（`--skip-media`，exclude 式更安全，不怕漏权重）。剩：放一个真 `icon.ico`（`--icon` 接线已就绪）。
3. 出 **release zip / exe**，写个给操作员的一页纸。
4. ✅ 已发独立 git remote：`https://github.com/dff652/modelscope-downloader.git`（默认分支 `main`）。剩：加 LICENSE。

## 构建方式：出 Windows exe 的几条路（2026-06-24 调研，**未决，先记录**）

**为什么现在这套折腾**：PyInstaller **不是把代码编译成原生二进制**，而是把**整个 Python 解释器 + 脚本打包**。后果：① 不能跨平台编译，**必须在 Windows 上 build**；② build 机必须装真 Python；③ 产物大（几十~上百 MB）、易被杀软误报。本会话真机首跑就栽在 ① + 一个 Windows 经典坑——`where python` 命中**微软商店 `python.exe` 别名占位**（`...\WindowsApps\python.exe`，不是真 Python，跑 `--version` 无输出）。`build.bat` 已加针对该坑的诊断。

**本机工具链现状**（决定哪条路能在 dev box 直接做）：x86_64 Linux，**有 Docker**，**无** Go / Rust / Wine / mingw（gcc 有）。

| 方案 | Windows 是否要装 Python | 产物 | 取舍 | 本机可否直接做 |
|---|---|---|---|---|
| **A. 本机 Docker+Wine 打包** | 否（在 Linux 出 exe） | pyinstaller 包（大） | **复用现有 app.py**，无需任何 Windows；Wine 偶有怪癖，成品建议真机抽测一次；容器内 pip 也要配国内镜像 | ✅ Docker 已在，可直接试（镜像 `tobix/pywine` 或 `cdrx/pyinstaller-windows`） |
| **B. Go 重写 + 交叉编译** | 否 | **真·原生小 exe ~10MB**，无 Python / 无杀软误报 / 无 hidden-import | 要用 Go 重实现 ModelScope 下载协议（hub HTTP API：列文件→逐个下→续传，现在最稳那部分会被重写，有协议对不上的风险）+ 简单 GUI（`lxn/walk` 纯 Go、无 cgo、可从 Linux 交叉编译） | 需先装 Go（apt 或 golang Docker 镜像） |
| **C. GitHub Actions** | 否（CI 真 Windows build） | pyinstaller 包 | 最规范、真 Windows 环境；需 GitHub remote + 外网，迭代慢 | 需联网 + 推仓库 |

**建议**：先 **A**（最快拿到可用 exe，复用已验证代码，操作员机彻底不碰 Python）；若嫌 pyinstaller 包重 / 被杀软盯，再上 **B**（终极干净小二进制）。**Nuitka** 也能编译，但仍需 Windows + C 编译器，不解决跨平台问题，略。

## 关联

- CLI 版源（ts-platform 内）：`ts-platform/scripts/tools/modelscope-download/` + 起点 `ts-platform/docs/handoffs/win10-modelscope-tool-start-here.md`
- 为什么要取这些模型 / 测试模型怎么选：`ts-platform/docs/handbooks/vllm-ascend-model-support.md`
- 910C 推理 bring-up 上下文：`ts-platform/docs/handoffs/ascend-inference-start-here.md`
