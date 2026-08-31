# ModelScope Downloader

给非技术操作员的「双击下载 ModelScope 模型」小工具。用途：**air-gapped 部署机没外网，模型在联网机下好 → 普通模型打 tar 或超大模型分批搬运 → 传过去**。

- **双击 exe / 无参数** → 弹 GUI（填模型 id、选文件夹、点下载）。
- **带参数** → 命令行（power user / Linux / 脚本）。
- 断点续传、并行（视 modelscope 版本支持）、网络出错自动重试。
- **下完一键打包**成 `.tar` + `.sha256`（操作员全程不用开终端）。
- **超大模型离线分批**：按容量把完整文件分到 `batch-001/` 等目录，逐批搬运、SHA256 校验，绝不切割或拼接权重文件。

> 发布状态（2026-08-31）：v0.4.0 当前按 release candidate 处理；是否已公开发布、可下载的 EXE 和具体资产，以 GitHub [Releases](https://github.com/dff652/modelscope-downloader/releases) 页面为准。下文的分批说明只有在对应 Release/CI 资产可用时才交付操作员；稳定版交付前仍需真 Windows GUI 点验。

## 给操作员（用 exe）

1. 拿到 `ModelScopeDownloader.exe`，**双击**。
2. 在「模型 id」里下拉选常用，或直接粘贴（如 `Qwen/Qwen3-0.6B`）。
3. 「保存到文件夹」点**浏览…**选个盘大的目录（300G 模型要 ≥350G 空；若要顺手打包再留同等空间）。工具下载前会自动查模型大小，**盘不够会在日志里预警**。
4.（可选）勾「跳过图片/视频等演示文件」更快更省盘——推理用不到这些。
5. 点 **下载 / Download**。有**进度条 + 百分比 + 网速 + 预计剩余时间**（刚开始「查询清单/连接」阶段短暂无进度是正常的）。随时可点**停止**；**断网/停止/关了重开，再点下载即从断点续传。**
6. 完成会问「现在打包成 .tar 吗？」选**是**，工具自动生成 `<模型>.tar` 和 `<模型>.tar.sha256`。
   （模型会下到所选文件夹里的 `<模型>/` 子目录；打出的 `.tar`/`.sha256` 就在所选文件夹中、与该子目录并排。）
7. 把这**两个文件**一起拷到部署机即可（校验/解包见下方「排错」）。

### 超大模型：离线分批搬运

模型最终大小超过下载机或移动盘容量、但离线服务器空间足够时，使用分批模式。它只改变搬运方式，**不能减少服务器最终需要的总空间**，也不要求操作员手动导出或拼接模型文件。

1. 勾选「**离线分批下载**」，填写「每批上限(GB)」和「下载第」批次。界面默认每批上限为 100；先下载第 1 批。
2. 点下载后，工具先读取远端文件清单，按稳定路径排序，把**完整文件**分组，并显示「共 N 批；当前第 K 批」。N 是工具根据文件大小自动算出的，界面没有另填总批数的输入框；K 必须是 1 到 N 的整数。
3. 每批上限是目标值而不是切割指令：多数批次不会超过该上限；单个文件超过上限时会独占一批，仍不会切割 `.safetensors` 等权重文件。
4. 首次规划会写入 `_OFFLINE-BATCH-PLAN.json`，锁定模型、revision、过滤条件、批大小、文件名/大小和可用的远端 SHA256。后续批次必须复用同一保存目录和设置，防止跨天混入新版文件。
5. 本批完成后，把整个 `<模型>/batch-001/` 搬到移动盘或其他离线介质。目录内自带本批 SHA256、纯 Python 校验脚本和服务器命令说明；不需要手动导出模型文件。
6. 在服务器按 `_OFFLINE-SERVER-INSTRUCTIONS.txt` 把本批**文件复制**到同一个最终模型目录并校验。复制是目录合并，不是把权重内容拼成新文件；禁止用 `cat` / `copy /b` 拼接。每批显示 `failed=0` 后，才删除下载机/移动盘上的本批以释放空间。
7. GUI 完成一批会自动把批次输入框切到下一批。全部批次上传并逐批校验后，再按说明运行总校验。

#### 批次大小和批次数怎么定

- 工具只接受大于 0 的批大小；没有强制最大值，也不会替你检查移动盘是否真的有足够余量。界面显示 GB，内部按 `1024^3` 字节换算。
- 实际批大小按「移动介质可用空间」和「下载机可用空间」两者中较小者来定，并预留约 10%–20% 余量。50–100GB 是常见的保守起点；500GB 磁盘不要把批大小设到接近剩余空间。
- 总批数 N 由清单和完整文件大小自动决定，不能保证恰好分成指定数量。若某个单文件本身大于移动介质或目标盘可用空间，分批也无法解决，必须换更大介质/目标盘或采用可达的在线传输路径。
- 重新运行同一批会沿用断点续传；不要中途改模型、revision、过滤条件、保存目录或每批大小。要建立新计划，请另选保存目录。

CLI 正式搬运仍建议使用不可变 tag/commit 的 `--revision`。若只能使用持续变化的默认分支，工具会复用首批计划，并在远端提供 SHA256 时拒绝混入后来变更的同名文件。

批次目录示例：

```text
<保存目录>/<模型名>/
├── batch-001/              # 第 1 批完整模型文件 + 校验/说明
├── batch-002/              # 第 2 批；上一批上传校验后可从下载机删除
├── _OFFLINE-BATCH-PLAN.txt
└── _OFFLINE-SERVER-INSTRUCTIONS.txt
```

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
# 离线分批：自动规划每批约 100GB，先下载第 1 批；下一次把批次号改成 2
python app.py --model owner/700B-model --revision <固定版本> --out ./staging/700B --batch-size-gb 100 --batch-number 1 --skip-media
# 同一计划的下一批（沿用 ./staging/700B/_OFFLINE-BATCH-PLAN.json）
python app.py --model owner/700B-model --revision <固定版本> --out ./staging/700B --batch-size-gb 100 --batch-number 2 --skip-media
```
参数：`--include "*.safetensors" "*.json"` / `--exclude` / `--skip-media`（跳过图片视频等演示文件）/ `--batch-size-gb` + `--batch-number`（离线分批；前者必须大于 0，后者从 1 开始且不能超过自动计算的 N）/ `--tar`（完整下载后打包成 .tar+.sha256；不能与分批同时使用）/ `--revision` / `--token`（受限模型）/ `--retries`。

每批上传服务器时，直接执行该批 `_OFFLINE-SERVER-INSTRUCTIONS.txt` 中按实际路径生成的命令。校验器只用 Python 标准库，不访问 ModelScope；Linux 服务器需要 `python3`，Windows 服务器需要 `python`/Python 3。以下示例中的路径和 `<总批数>` 要替换成实际值。

Linux 每批（示例为 batch-001）：

```bash
mkdir -p /srv/models/<模型名>/.offline-batches
rsync -av --exclude='_OFFLINE-*' /media/usb/batch-001/ /srv/models/<模型名>/
cp /media/usb/batch-001/_OFFLINE-SHA256SUMS.batch-001 /srv/models/<模型名>/.offline-batches/
cp /media/usb/batch-001/_OFFLINE-VERIFY.py /srv/models/<模型名>/.offline-batches/
cd /srv/models/<模型名>
python3 .offline-batches/_OFFLINE-VERIFY.py . .offline-batches/_OFFLINE-SHA256SUMS.batch-001
```

Windows PowerShell 每批（示例为 batch-001）：

```powershell
robocopy E:\batch-001 D:\models\<模型名> /E /XF _OFFLINE-*
New-Item -ItemType Directory -Force D:\models\<模型名>\.offline-batches | Out-Null
Copy-Item E:\batch-001\_OFFLINE-SHA256SUMS.batch-001 D:\models\<模型名>\.offline-batches\ -Force
Copy-Item E:\batch-001\_OFFLINE-VERIFY.py D:\models\<模型名>\.offline-batches\ -Force
python D:\models\<模型名>\.offline-batches\_OFFLINE-VERIFY.py D:\models\<模型名> D:\models\<模型名>\.offline-batches\_OFFLINE-SHA256SUMS.batch-001
```

每批的校验必须输出 `failed=0`。`robocopy` 的复制结果也要留意；校验失败、文件缺失或路径写错时不要删除介质上的批次。

全部 N 批到齐后，Linux 服务器的最终校验形如（下面以 N=2 为例；工具生成的说明会枚举实际全部文件名）：

```bash
cd /srv/models/<模型名>
for f in .offline-batches/_OFFLINE-SHA256SUMS.batch-001 .offline-batches/_OFFLINE-SHA256SUMS.batch-002; do test -f "$f" || { echo "缺少 $f"; exit 1; }; done
test "$(find .offline-batches -maxdepth 1 -type f -name '_OFFLINE-SHA256SUMS.batch-*' | wc -l)" -eq 2 || { echo "批次校验清单总数不是 2"; exit 1; }
python3 .offline-batches/_OFFLINE-VERIFY.py . .offline-batches/_OFFLINE-SHA256SUMS.batch-001 .offline-batches/_OFFLINE-SHA256SUMS.batch-002
```

全部 N 批到齐后，Windows PowerShell 的最终校验形如（以 N=2 为例）：

```powershell
$root='D:\models\<模型名>'
$sums=@("$root\.offline-batches\_OFFLINE-SHA256SUMS.batch-001", "$root\.offline-batches\_OFFLINE-SHA256SUMS.batch-002")
$missing=@($sums | Where-Object { -not (Test-Path $_ -PathType Leaf) })
if ($missing.Count) { throw "缺少批次校验清单：$($missing -join ', ')" }
$actual=@(Get-ChildItem "$root\.offline-batches\_OFFLINE-SHA256SUMS.batch-*")
if ($actual.Count -ne 2) { throw "批次校验清单数量不对：$($actual.Count)/2" }
python "$root\.offline-batches\_OFFLINE-VERIFY.py" $root $sums
```

最终验收同时确认模型配置、tokenizer、权重 index（如有）及全部权重分片都在同一模型目录；只有最终命令输出 `failed=0` 后，才清理剩余搬运介质。

## 排错

| 现象 | 解决 |
|---|---|
| 断网 / 中断 | 重新下载同一模型即从断点续传 |
| 点下载后弹出 `pyi_rth__tkinter` / `_tcl_data not found` | 这是 EXE 临时解包资源异常，尚未进入模型下载。关闭所有 ModelScope Downloader 窗口后重新打开；若反复出现，检查 Defender 隔离记录和临时目录清理软件，并将完整弹窗截图发给开发者 |
| 盘满 | 换大盘；300G 模型放 NTFS ≥350G |
| 长路径报错 | 保存目录用**短路径**（如 `D:\m\xxx`） |
| `model not found` / 404 | 核对 model id（区分大小写；有的没 `-Instruct` 后缀） |
| 受限模型 403 | 命令行加 `--token <SDK_TOKEN>`（modelscope.cn 个人中心拿） |
| 打包/拷贝后想验完整性 | 部署机上把 `.tar` 和 `.tar.sha256` 放一起跑 `sha256sum -c <模型>.tar.sha256`（显示 `成功/OK` 即一致） |
| 部署机解包 | `tar -xf <模型>.tar`（解出 `<模型>/` 目录，里面就是模型） |
| 分批时单个文件超过每批上限 | 正常：该文件会独占一批；如果仍放不进移动介质，只能换更大介质/目标盘 |
| 分批服务器校验失败 | 保留本批介质，检查是否完整复制到同一最终目录、路径是否正确；修复后重新执行 `_OFFLINE-VERIFY.py` |

## 常用 model id

| id | 说明 |
|---|---|
| `Qwen/Qwen3-0.6B` | 小模型 / 跨卡测试 |
| `Eco-Tech/DeepSeek-V4-Flash-w8a8-mtp` | V4-Flash 主选 ~300G |
| `gdydems/DeepSeek-V4-Flash-w4a8-mtp` | V4-Flash 省盘 ~162G |

---
开发者：见 [START-HERE.md](START-HERE.md)。本项目从 `ts-platform` 的 `scripts/tools/modelscope-download/`（CLI 版）拆出独立化。
