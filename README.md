# ModelScope Downloader

给非技术操作员的「双击下载 ModelScope 模型」小工具。用途：**air-gapped 部署机没外网，模型在联网机下好 → 打 tar → 传过去**。

- **双击 exe / 无参数** → 弹 GUI（填模型 id、选文件夹、点下载）。
- **带参数** → 命令行（power user / Linux / 脚本）。
- 断点续传、并行、网络出错自动重试。

## 给操作员（用 exe）

1. 拿到 `ModelScopeDownloader.exe`，**双击**。
2. 在「模型 id」里下拉选常用，或直接粘贴（如 `Qwen/Qwen3-0.6B`）。
3. 「保存到文件夹」点**浏览…**选个盘大的目录（300G 模型要 ≥350G 空）。
4. 点 **下载 / Download**，等完成弹窗。**断网/关了重开再点下载即续传。**
5. 完成弹窗会给一行 `tar` 命令，按它把模型打包，再传部署机。

## 给打包者（在 Windows 上出 exe）

```bat
build.bat
:: 产物: dist\ModelScopeDownloader.exe (--onefile --windowed --collect-all modelscope)
```
需要 Python 3.10+（python.org，勾 Add to PATH）。首次构建会装 pyinstaller + modelscope。

## 命令行（power user / Linux）

```bash
pip install -U modelscope
python app.py --model Qwen/Qwen3-0.6B --out ./models/Qwen3-0.6B
# 300G: python app.py --model Eco-Tech/DeepSeek-V4-Flash-w8a8-mtp --out D:\models\v4flash
```
参数：`--include "*.safetensors" "*.json"` / `--exclude` / `--revision` / `--token`（受限模型）/ `--retries`。

## 排错

| 现象 | 解决 |
|---|---|
| 断网 / 中断 | 重新下载同一模型即从断点续传 |
| 盘满 | 换大盘；300G 模型放 NTFS ≥350G |
| 长路径报错 | 保存目录用**短路径**（如 `D:\m\xxx`） |
| `model not found` / 404 | 核对 model id（区分大小写；有的没 `-Instruct` 后缀） |
| 受限模型 403 | 命令行加 `--token <SDK_TOKEN>`（modelscope.cn 个人中心拿） |

## 常用 model id

| id | 说明 |
|---|---|
| `Qwen/Qwen3-0.6B` | 小模型 / 跨卡测试 |
| `Eco-Tech/DeepSeek-V4-Flash-w8a8-mtp` | V4-Flash 主选 ~300G |
| `gdydems/DeepSeek-V4-Flash-w4a8-mtp` | V4-Flash 省盘 ~162G |

---
开发者：见 [START-HERE.md](START-HERE.md)。本项目从 `ts-platform` 的 `scripts/tools/modelscope-download/`（CLI 版）拆出独立化。
