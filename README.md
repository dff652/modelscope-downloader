# ModelScope Downloader

给非技术操作员的「双击下载 ModelScope 模型」小工具。用途：**air-gapped 部署机没外网，模型在联网机下好 → 打 tar → 传过去**。

- **双击 exe / 无参数** → 弹 GUI（填模型 id、选文件夹、点下载）。
- **带参数** → 命令行（power user / Linux / 脚本）。
- 断点续传、并行（视 modelscope 版本支持）、网络出错自动重试。
- **下完一键打包**成 `.tar` + `.sha256`（操作员全程不用开终端）。

## 给操作员（用 exe）

1. 拿到 `ModelScopeDownloader.exe`，**双击**。
2. 在「模型 id」里下拉选常用，或直接粘贴（如 `Qwen/Qwen3-0.6B`）。
3. 「保存到文件夹」点**浏览…**选个盘大的目录（300G 模型要 ≥350G 空；若要顺手打包再留同等空间）。
4.（可选）勾「跳过图片/视频等演示文件」更快更省盘——推理用不到这些。
5. 点 **下载 / Download**，等完成弹窗。**断网/关了重开再点下载即续传。**
6. 完成会问「现在打包成 .tar 吗？」选**是**，工具自动生成 `<模型>.tar` 和 `<模型>.tar.sha256`。
   （模型会下到所选文件夹里的 `<模型>/` 子目录；打出的 `.tar`/`.sha256` 就在所选文件夹中、与该子目录并排。）
7. 把这**两个文件**一起拷到部署机即可（校验/解包见下方「排错」）。

## 给打包者（在 Windows 上出 exe）

```bat
build.bat
:: 产物: dist\ModelScopeDownloader.exe (--onefile --windowed --name ModelScopeDownloader --collect-all modelscope)
```
需要 **64 位** Python（python.org，勾 Add to PATH；32 位会被脚本拦下）。建议 **3.11**，与 build.bat 提示一致。首次构建会装 pyinstaller + modelscope（只装 hub 轻量包，不拉 torch）。

`build.bat` 已做好排错：
- **全程写 `build.log`**——失败时自动把真实报错打到屏幕，并提示日志路径（卡住就把 `build.log` 发给开发者）。
- **国内网络友好**：先连默认 PyPI，失败**自动换清华镜像重试**；两次都败会给出可复制的镜像/代理/SSL 排错命令。
- 构建后校验 `dist\ModelScopeDownloader.exe` 是否还在（被杀软误删会提示）。
- 放个 `icon.ico` 在脚本旁即自动加图标。

## 命令行（power user / Linux）

```bash
pip install -U modelscope
python app.py --model Qwen/Qwen3-0.6B --out ./models/Qwen3-0.6B
# 下完顺手打包 + 跳过演示文件：
python app.py --model Qwen/Qwen3-0.6B --out ./models/Qwen3-0.6B --skip-media --tar
# 300G: python app.py --model Eco-Tech/DeepSeek-V4-Flash-w8a8-mtp --out D:\models\v4flash --tar
```
参数：`--include "*.safetensors" "*.json"` / `--exclude` / `--skip-media`（跳过图片视频等演示文件）/ `--tar`（下完打包成 .tar+.sha256）/ `--revision` / `--token`（受限模型）/ `--retries`。

## 排错

| 现象 | 解决 |
|---|---|
| 断网 / 中断 | 重新下载同一模型即从断点续传 |
| 盘满 | 换大盘；300G 模型放 NTFS ≥350G |
| 长路径报错 | 保存目录用**短路径**（如 `D:\m\xxx`） |
| `model not found` / 404 | 核对 model id（区分大小写；有的没 `-Instruct` 后缀） |
| 受限模型 403 | 命令行加 `--token <SDK_TOKEN>`（modelscope.cn 个人中心拿） |
| 打包/拷贝后想验完整性 | 部署机上把 `.tar` 和 `.tar.sha256` 放一起跑 `sha256sum -c <模型>.tar.sha256`（显示 `成功/OK` 即一致） |
| 部署机解包 | `tar -xf <模型>.tar`（解出 `<模型>/` 目录，里面就是模型） |

## 常用 model id

| id | 说明 |
|---|---|
| `Qwen/Qwen3-0.6B` | 小模型 / 跨卡测试 |
| `Eco-Tech/DeepSeek-V4-Flash-w8a8-mtp` | V4-Flash 主选 ~300G |
| `gdydems/DeepSeek-V4-Flash-w4a8-mtp` | V4-Flash 省盘 ~162G |

---
开发者：见 [START-HERE.md](START-HERE.md)。本项目从 `ts-platform` 的 `scripts/tools/modelscope-download/`（CLI 版）拆出独立化。
