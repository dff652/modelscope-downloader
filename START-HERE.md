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

- ✅ **`app.py` 写好**：`download()` 引擎（`snapshot_download` + 断点续传 + 重试 + `max_workers` 探测）；CLI（argparse）；GUI（tkinter：模型 id 下拉/粘贴、文件夹浏览、下载、日志框、`dir_size` 轮询当进度、完成/失败弹窗给 tar 提示、worker 线程 + `queue`→`root.after` 线程安全刷新）。
- ✅ **dev box 语法验过**（`ast.parse` / `python -m py_compile`）。
- ✅ **核心下载逻辑已实证**：同款 `snapshot_download` 封装在 ts-platform 侧实际下成了 `Qwen/Qwen3-0.6B`、`Qwen/Qwen3.5-0.8B`（modelscope.cn 可达、续传可用）。
- ✅ `build.bat` 写好（含 `--collect-all modelscope` 应对动态导入）。

## ⚠️ 未做 / 未测（**关键，下个会话先干这些**）

1. **GUI 没在真 Windows 上跑过**：tkinter 行为、文件夹选择、弹窗、线程刷新都只在逻辑上正确，**待真机验证**（dev box 是 Linux 无显示，跑不了 GUI）。
2. **exe 没在 Windows 构建/测过**：`pyinstaller --collect-all modelscope` 多半还**缺 hidden-imports**（modelscope 动态 import 多），首次构建大概率要补 `--hidden-import` 或 `--collect-submodules`；exe 体积会很大（modelscope 依赖重）。**这是最大未知**。
3. 进度是 `dir_size` 轮询（**粗略**），不是真百分比；tqdm 在 `--windowed` 无 console 不显示（故才用轮询）。可改成解析 modelscope 回调/总大小。
4. 无图标 / 无签名（Windows SmartScreen 可能拦未签名 exe，要让操作员「仍要运行」）。
5. 无自动更新 / 版本检查；无 LICENSE。

## 下一步（开发待办，按优先级）

1. **在一台真 Windows 上跑 `build.bat`** → 修 pyinstaller 缺的 hidden-imports（看 exe 运行时报的 `ModuleNotFoundError` 逐个补），直到双击能开 GUI + 下成一个小模型。把可用的 pyinstaller flags/`.spec` 固化回 `build.bat`。
2. GUI 跑通后：加图标（`--icon`）、加「下载完自动打 tar + 出 sha256」按钮、`--include` 预设（只下 safetensors+config，跳 video/preprocessor）。
3. 出 **release zip / exe**，写个给操作员的一页纸。
4. （可选）发独立 git remote。

## 关联

- CLI 版源（ts-platform 内）：`ts-platform/scripts/tools/modelscope-download/` + 起点 `ts-platform/docs/handoffs/win10-modelscope-tool-start-here.md`
- 为什么要取这些模型 / 测试模型怎么选：`ts-platform/docs/handbooks/vllm-ascend-model-support.md`
- 910C 推理 bring-up 上下文：`ts-platform/docs/handoffs/ascend-inference-start-here.md`
