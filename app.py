#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ModelScope Downloader — 给非技术操作员的双击工具。

- 双击 exe / 无参数运行 → 弹出 GUI（填模型 id + 选文件夹 + 点 Download）。
- 带参数运行 → 命令行模式（power user / Linux / 脚本）。

用途：air-gapped 部署机没外网，模型在联网机下好 → 打 tar → 传过去。
依赖：modelscope（`pip install -U modelscope`）。打 Windows exe 见 build.bat（pyinstaller）。
"""
import argparse
import os
import sys
import threading
import time

APP_TITLE = "ModelScope Downloader"
APP_VERSION = "0.4.0"
APP_AUTHOR = "dff652"
APP_URL = "https://github.com/dff652/modelscope-downloader"


def _harden_stdio():
    """中文输出防崩：stdout/stderr 编不出的字符改打 '?'，不抛 UnicodeEncodeError。

    场景：CLI 输出全是中文，但控制台/管道编码不一定认中文
    （如英文 Windows 的 cp1252、CI 的重定向管道）——不加固则 print 直接崩。
    """
    for s in (sys.stdout, sys.stderr):
        try:
            if s is not None and hasattr(s, "reconfigure"):
                s.reconfigure(errors="replace")
        except Exception:  # noqa: BLE001 — 加固失败就保持原样，别反过来弄崩程序
            pass

# 常用模型预设（GUI 下拉 / 提示用）
PRESETS = [
    ("Qwen/Qwen3-0.6B", "小模型 / 跨卡测试"),
    ("Eco-Tech/DeepSeek-V4-Flash-w8a8-mtp", "V4-Flash 主选 ~300G"),
    ("gdydems/DeepSeek-V4-Flash-w4a8-mtp", "V4-Flash 省盘 ~162G"),
]

# 推理用不到的图片/视频/音频等演示文件（--skip-media / GUI 勾选 → 当 ignore_patterns）
MEDIA_EXCLUDE = [
    "*.png", "*.jpg", "*.jpeg", "*.gif", "*.bmp", "*.webp", "*.tiff", "*.ico", "*.svg",
    "*.mp4", "*.avi", "*.mov", "*.mkv", "*.webm", "*.mp3", "*.wav", "*.flac",
]


def human(n):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f}{u}"
        n /= 1024
    return f"{n:.1f}PB"


def batch_bytes_from_gb(value):
    """把 GUI/CLI 的 GB 输入安全转换为字节。"""
    import math
    if not math.isfinite(value) or value <= 0:
        raise ValueError("每批上限必须是大于 0 的有限数字")
    return max(1, int(value * 1024 ** 3))


def dir_size(p):
    total = 0
    for root, _, files in os.walk(p):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def model_manifest(model, include=None, exclude=None, revision=None, token=None):
    """查模型清单 → 文件字典列表；任何失败返回 None。"""
    import fnmatch
    try:
        try:
            # 新版公共 API 保留 revision 和 SHA256；分批计划优先用它锁定快照。
            from modelscope_hub.api import HubApi as ModernHubApi
            files = ModernHubApi(token=token).list_repo_files(
                model, "model", revision=revision, recursive=True)
            manifest = [{
                "path": f.path,
                "size": int(f.size or 0),
                "sha256": f.sha256 or None,
                "type": getattr(f, "type", "blob"),
            } for f in files]
        except (ImportError, AttributeError, TypeError):
            # modelscope < 1.38 没有独立 modelscope_hub，保留旧 API 兼容。
            from modelscope.hub.api import HubApi
            api = HubApi()
            if token:
                api.login(token)
            import inspect
            kw = {"recursive": True}
            if revision and "revision" in inspect.signature(api.get_model_files).parameters:
                kw["revision"] = revision
            files = api.get_model_files(model, **kw)
            manifest = [{
                "path": f.get("Path") or f.get("Name") or "",
                "size": int(f.get("Size") or 0),
                "sha256": f.get("Sha256") or f.get("sha256") or None,
                "type": f.get("Type") or "blob",
            } for f in files]

        filtered = []
        for item in manifest:
            path = item["path"]
            if item["type"] == "tree" or not path:
                continue
            if include and not any(fnmatch.fnmatch(path, p) for p in include):
                continue
            if exclude and any(fnmatch.fnmatch(path, p) for p in exclude):
                continue
            item.pop("type", None)
            filtered.append(item)
        return sorted(filtered, key=lambda item: item["path"]) or None
    except Exception:  # noqa: BLE001 — 清单查不到就不显示百分比，下载照常
        return None


def expected_total(model, include=None, exclude=None, revision=None, token=None):
    """查模型清单 → (总字节数, 文件数)；任何失败返回 None。"""
    manifest = model_manifest(model, include=include, exclude=exclude,
                              revision=revision, token=token)
    if not manifest:
        return None
    return sum(item["size"] for item in manifest), len(manifest)


def plan_batches(manifest, batch_bytes):
    """按完整文件顺序分批；单文件超过上限时独占一批，不切割文件。"""
    if batch_bytes <= 0:
        raise ValueError("每批大小必须大于 0")
    batches, current, current_size = [], [], 0
    for item in sorted(manifest, key=lambda entry: entry["path"]):
        size = item["size"]
        if current and current_size + size > batch_bytes:
            batches.append(current)
            current, current_size = [], 0
        current.append(item)
        current_size += size
        if size > batch_bytes:
            batches.append(current)
            current, current_size = [], 0
    if current:
        batches.append(current)
    return batches


def load_or_create_batch_plan(model_root, model, revision, include, exclude,
                              batch_bytes, token=None):
    """首批锁定文件清单；后续批次复用，避免跨天混入仓库新版本。"""
    import json
    plan_path = os.path.join(model_root, "_OFFLINE-BATCH-PLAN.json")
    settings = {
        "format_version": 1,
        "model": model,
        "revision": revision,
        "include": list(include or []),
        "exclude": list(exclude or []),
        "batch_bytes": batch_bytes,
    }
    if os.path.isfile(plan_path):
        with open(plan_path, "r", encoding="utf-8") as f:
            saved = json.load(f)
        for key, expected in settings.items():
            if saved.get(key) != expected:
                raise ValueError(
                    f"已有批次计划与当前 {key} 不一致。为避免混合模型版本，"
                    "请恢复原设置，或为新计划选择另一个保存目录。")
        batches = saved.get("batches")
        if not isinstance(batches, list) or not batches:
            raise ValueError(f"批次计划损坏：{plan_path}")
        return batches, plan_path, False

    manifest = model_manifest(model, include=include, exclude=exclude,
                              revision=revision, token=token)
    if not manifest:
        raise RuntimeError("无法取得模型文件清单，不能安全规划离线批次")
    batches = plan_batches(manifest, batch_bytes)
    os.makedirs(model_root, exist_ok=True)
    payload = dict(settings, batches=batches)
    temp_path = plan_path + ".tmp"
    with open(temp_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(temp_path, plan_path)
    return batches, plan_path, True


def _safe_local_file(root, relative_path):
    """把仓库内 POSIX 路径安全映射到本地批次目录。"""
    from pathlib import PurePosixPath
    rel = PurePosixPath(relative_path.replace("\\", "/"))
    if rel.is_absolute() or ".." in rel.parts or (rel.parts and ":" in rel.parts[0]):
        raise ValueError(f"不安全的模型文件路径：{relative_path}")
    return os.path.join(root, *rel.parts)


def _sha256_file(path):
    import hashlib
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(8 * 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


_OFFLINE_VERIFY_SCRIPT = r'''#!/usr/bin/env python3
"""Verify offline model batches using only Python's standard library."""
import hashlib
from pathlib import Path, PurePosixPath
import sys


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(8 * 1024 * 1024)
            if not chunk:
                return value.hexdigest()
            value.update(chunk)


def main():
    if len(sys.argv) < 3:
        print("usage: python _OFFLINE-VERIFY.py <model-dir> <SHA256SUMS> [...]", file=sys.stderr)
        return 2
    root = Path(sys.argv[1])
    checked = failed = 0
    for manifest_name in sys.argv[2:]:
        manifest = Path(manifest_name)
        for raw in manifest.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            expected, rel_text = raw.split("  ", 1)
            rel = PurePosixPath(rel_text)
            if rel.is_absolute() or ".." in rel.parts or (rel.parts and ":" in rel.parts[0]):
                print(f"[x] unsafe path: {rel_text}")
                failed += 1
                continue
            path = root.joinpath(*rel.parts)
            checked += 1
            if not path.is_file():
                print(f"[x] missing: {rel_text}")
                failed += 1
            elif digest(path) != expected:
                print(f"[x] mismatch: {rel_text}")
                failed += 1
            else:
                print(f"[ok] {rel_text}")
    print(f"checked={checked} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def write_offline_batch_artifacts(model_root, batch_dir, model, revision,
                                  batches, batch_number, batch_bytes, log=print):
    """为一个已完成批次生成校验清单、总计划和离线服务器操作说明。"""
    os.makedirs(model_root, exist_ok=True)
    os.makedirs(batch_dir, exist_ok=True)
    selected = batches[batch_number - 1]
    checksum_name = f"_OFFLINE-SHA256SUMS.batch-{batch_number:03d}"
    checksum_path = os.path.join(batch_dir, checksum_name)
    log(f"[*] 正在生成第 {batch_number} 批 SHA256（大批次会花一些时间）")
    with open(checksum_path, "w", encoding="utf-8", newline="\n") as f:
        for item in selected:
            path = _safe_local_file(batch_dir, item["path"])
            if not os.path.isfile(path):
                raise FileNotFoundError(f"批次文件缺失：{item['path']}")
            actual = _sha256_file(path)
            expected = item.get("sha256")
            if expected and actual.lower() != expected.lower():
                raise ValueError(
                    f"{item['path']} 与首批锁定清单的 SHA256 不一致；"
                    "远端版本可能已变化，请固定原 revision 后重试")
            f.write(f"{actual}  {item['path'].replace(os.sep, '/')}\n")

    plan_lines = [
        "ModelScope Downloader 离线分批计划",
        f"模型：{model}",
        f"版本：{revision or '默认分支（首批文件清单和可用的远端 SHA256 已锁定）'}",
        f"每批上限：{human(batch_bytes)}",
        f"总批数：{len(batches)}",
        "说明：文件保持原样；不要 cat/copy /b 拼接 safetensors 分片。",
        "",
    ]
    for index, batch in enumerate(batches, 1):
        plan_lines.append(
            f"batch-{index:03d}: {len(batch)} 个文件，"
            f"{human(sum(item['size'] for item in batch))}")
        plan_lines.extend(f"  {item['path']}  {human(item['size'])}" for item in batch)
    plan_text = "\n".join(plan_lines) + "\n"

    model_name = model.split("/")[-1]
    batch_name = f"batch-{batch_number:03d}"
    checksum_names = [f"_OFFLINE-SHA256SUMS.batch-{index:03d}"
                      for index in range(1, len(batches) + 1)]
    linux_checksums = " ".join(
        f".offline-batches/{name}" for name in checksum_names)
    windows_checksums = ",\n    ".join(
        f"\"$root\\.offline-batches\\{name}\"" for name in checksum_names)
    instructions = f"""ModelScope Downloader 离线服务器操作说明

本批：{batch_number}/{len(batches)}（{batch_name}）
原则：每批目录中的模型文件复制到服务器同一个最终模型目录；不要拼接权重文件。

Linux 服务器（把 /media/usb 和 /srv/models/{model_name} 换成实际路径）：
  mkdir -p /srv/models/{model_name}/.offline-batches
  rsync -av --exclude='_OFFLINE-*' /media/usb/{batch_name}/ /srv/models/{model_name}/
  cp /media/usb/{batch_name}/{checksum_name} /srv/models/{model_name}/.offline-batches/
  cp /media/usb/{batch_name}/_OFFLINE-VERIFY.py /srv/models/{model_name}/.offline-batches/
  cd /srv/models/{model_name}
  python3 .offline-batches/_OFFLINE-VERIFY.py . .offline-batches/{checksum_name}

Windows 服务器（把 E: 和 D:\\models\\{model_name} 换成实际路径）：
  robocopy E:\\{batch_name} D:\\models\\{model_name} /E /XF _OFFLINE-*
  mkdir D:\\models\\{model_name}\\.offline-batches
  copy E:\\{batch_name}\\{checksum_name} D:\\models\\{model_name}\\.offline-batches\\
  copy E:\\{batch_name}\\_OFFLINE-VERIFY.py D:\\models\\{model_name}\\.offline-batches\\
  python D:\\models\\{model_name}\\.offline-batches\\_OFFLINE-VERIFY.py D:\\models\\{model_name} D:\\models\\{model_name}\\.offline-batches\\{checksum_name}

全部 {len(batches)} 批上传后，在 Linux 服务器执行：
  cd /srv/models/{model_name}
  for f in {linux_checksums}; do test -f "$f" || {{ echo "缺少 $f"; exit 1; }}; done
  test "$(find .offline-batches -maxdepth 1 -name '_OFFLINE-SHA256SUMS.batch-*' | wc -l)" -eq {len(batches)} || {{ echo "批次校验清单总数不是 {len(batches)}"; exit 1; }}
  python3 .offline-batches/_OFFLINE-VERIFY.py . {linux_checksums}

全部 {len(batches)} 批上传后，在 Windows PowerShell 执行：
  $root='D:\\models\\{model_name}'
  $sums=@(
    {windows_checksums}
  )
  $missing=@($sums | Where-Object {{ -not (Test-Path $_ -PathType Leaf) }})
  if ($missing.Count) {{ throw "缺少批次校验清单：$($missing -join ', ')" }}
  $actual=@(Get-ChildItem "$root\\.offline-batches\\_OFFLINE-SHA256SUMS.batch-*")
  if ($actual.Count -ne {len(batches)}) {{ throw "批次校验清单数量不对：$($actual.Count)/{len(batches)}" }}
  python "$root\\.offline-batches\\_OFFLINE-VERIFY.py" $root $sums

最后确认模型目录中存在配置、tokenizer、权重 index（如有）及全部权重分片。
只有全部批次校验通过后，才可删除下载机/移动盘上的批次。
"""

    artifacts = {
        "_OFFLINE-BATCH-PLAN.txt": plan_text,
        "_OFFLINE-SERVER-INSTRUCTIONS.txt": instructions,
        "_OFFLINE-VERIFY.py": _OFFLINE_VERIFY_SCRIPT,
    }
    for name, content in artifacts.items():
        with open(os.path.join(model_root, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        with open(os.path.join(batch_dir, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
    locked_plan = os.path.join(model_root, "_OFFLINE-BATCH-PLAN.json")
    if os.path.isfile(locked_plan):
        with open(locked_plan, "r", encoding="utf-8") as src:
            content = src.read()
        with open(os.path.join(batch_dir, "_OFFLINE-BATCH-PLAN.json"),
                  "w", encoding="utf-8", newline="\n") as dst:
            dst.write(content)
    log(f"[ok] 第 {batch_number}/{len(batches)} 批校验与离线说明已生成：{batch_dir}")
    return checksum_path


def free_disk(path):
    """path 所在盘的剩余字节数；失败返回 None。"""
    import shutil
    try:
        probe = path
        while probe and not os.path.exists(probe):
            probe = os.path.dirname(probe)
        return shutil.disk_usage(probe or ".").free
    except Exception:  # noqa: BLE001
        return None


def download(model, out, revision=None, include=None, exclude=None,
             token=None, retries=20, log=print):
    """核心：modelscope snapshot_download 封装 + 断点续传 + 自动重试。

    log 是日志回调（CLI 传 print；GUI 传往文本框塞行的函数）。返回最终目录。
    """
    try:
        # 直接导子模块：比 `from modelscope import ...`（走 LazyImportModule）轻，
        # 动态 import 少 → pyinstaller 更易打全（见 build.bat）。旧版本兜底用顶层。
        try:
            from modelscope.hub.snapshot_download import snapshot_download
        except ImportError:
            from modelscope import snapshot_download
    except ImportError:
        log("[x] 缺 modelscope。先装：pip install -U modelscope")
        raise

    if token:
        try:
            from modelscope.hub.api import HubApi
            HubApi().login(token)
            log("[*] 已登录 ModelScope")
        except Exception as e:  # noqa: BLE001
            log(f"[!] login 警告（忽略继续）：{e}")

    os.makedirs(out, exist_ok=True)
    kw = {"local_dir": out}
    if revision:
        kw["revision"] = revision
    if include:
        kw["allow_patterns"] = include
    if exclude:
        kw["ignore_patterns"] = exclude
    try:
        import inspect
        if "max_workers" in inspect.signature(snapshot_download).parameters:
            kw["max_workers"] = 4
    except (ValueError, TypeError):
        pass

    log(f"[*] 下载 {model}  ->  {out}")
    log("    （中断/断网后，重跑同样的下载即续传）")
    attempt = 0
    while True:
        attempt += 1
        try:
            path = snapshot_download(model, **kw)
            break
        except Exception as e:  # noqa: BLE001
            if attempt >= retries:
                log(f"[x] 第 {attempt} 次仍失败：{e}")
                raise
            wait = min(30, 2 ** min(attempt, 5))
            log(f"[!] [{attempt}/{retries}] 出错：{e} — {wait}s 后重试")
            time.sleep(wait)

    log(f"[ok] 完成：{path}")
    log(f"     本地大小：{human(dir_size(out))}")
    base = os.path.basename(os.path.normpath(out))
    parent = os.path.dirname(os.path.normpath(out)) or "."
    log(f"     打包传机：tar -cf \"{base}.tar\" -C \"{parent}\" \"{base}\"")
    return path


def make_archive(src_dir, log=print):
    """把下好的模型目录打成 <dir>.tar + 同名 .sha256（操作员免开终端）。

    不压缩（safetensors 等权重本就难压，纯打包最快）；边写边算 sha256，避免回读。
    返回 tar 路径。注意：需要与模型同等大小的额外磁盘空间。
    """
    import hashlib
    import tarfile

    src_dir = os.path.normpath(src_dir)
    base = os.path.basename(src_dir)
    parent = os.path.dirname(src_dir) or "."
    tar_path = os.path.join(parent, base + ".tar")
    sha_path = tar_path + ".sha256"

    log(f"[*] 打包 {src_dir}")
    log(f"    -> {tar_path}")
    log("    （需与模型同等大小的额外磁盘空间；大模型可能数分钟）")

    class _HashingFile:
        """包装写入流：write 时顺带喂 sha256，其余方法透传给底层文件。"""

        def __init__(self, f):
            self._f = f
            self.h = hashlib.sha256()

        def write(self, data):
            self.h.update(data)
            return self._f.write(data)

        def __getattr__(self, name):
            return getattr(self._f, name)

    with open(tar_path, "wb") as raw:
        hw = _HashingFile(raw)
        # 流式写 "w|"：只顺序写、不回退 seek，sha256 与落盘字节一致
        with tarfile.open(fileobj=hw, mode="w|") as tf:
            tf.add(src_dir, arcname=base)
        digest = hw.h.hexdigest()

    with open(sha_path, "w", encoding="utf-8") as f:
        f.write(f"{digest}  {base}.tar\n")

    log(f"[ok] 打包完成：{tar_path}")
    log(f"     大小：{human(os.path.getsize(tar_path))}")
    log(f"     SHA256：{digest}")
    log(f"     部署机核对：把 {base}.tar 和 {base}.tar.sha256 放一起，跑  sha256sum -c {base}.tar.sha256")
    log(f"     解包：tar -xf {base}.tar")
    return tar_path


# ───────────────────────────── CLI ─────────────────────────────
def run_cli(argv):
    ap = argparse.ArgumentParser(prog="modelscope-downloader",
                                 description="ModelScope 模型下载（断点续传）",
                                 epilog=f"v{APP_VERSION} · 作者 {APP_AUTHOR} · {APP_URL}")
    ap.add_argument("--model", required=True, help="模型 id，如 Qwen/Qwen3-0.6B")
    ap.add_argument("--out", required=True, help="本地目标目录（建议短路径）")
    ap.add_argument("--include", nargs="*", default=None, help="只下匹配 glob")
    ap.add_argument("--exclude", nargs="*", default=None, help="跳过匹配 glob")
    ap.add_argument("--revision", default=None, help="版本/分支")
    ap.add_argument("--token", default=None, help="受限模型才需要")
    ap.add_argument("--retries", type=int, default=20)
    ap.add_argument("--batch-size-gb", type=float, default=None,
                    help="离线分批：每批上限 GB（完整文件分组，不切割权重文件）")
    ap.add_argument("--batch-number", type=int, default=1,
                    help="离线分批：下载第几批（从 1 开始）")
    ap.add_argument("--skip-media", action="store_true",
                    help="跳过图片/视频/音频等演示文件（推理用不到，更快更省盘）")
    ap.add_argument("--tar", action="store_true",
                    help="下完自动打包成 .tar + .sha256（便于传 air-gapped 机）")
    a = ap.parse_args(argv)
    exclude = list(a.exclude) if a.exclude else []
    if a.skip_media:
        exclude += MEDIA_EXCLUDE
    if a.batch_number < 1:
        ap.error("--batch-number 必须从 1 开始")
    batch_bytes = None
    if a.batch_size_gb is not None:
        try:
            batch_bytes = batch_bytes_from_gb(a.batch_size_gb)
        except ValueError as e:
            ap.error(str(e))
    if a.batch_size_gb is None and a.batch_number != 1:
        ap.error("使用 --batch-number 时必须同时提供 --batch-size-gb")
    if a.batch_size_gb is not None and a.tar:
        ap.error("离线分批模式不能使用 --tar；每批目录可直接搬运")

    target = a.out
    selected_include = a.include
    batches = None
    if a.batch_size_gb is not None:
        try:
            batches, plan_path, created = load_or_create_batch_plan(
                a.out, a.model, a.revision, a.include, (exclude or None),
                batch_bytes, token=a.token)
        except (RuntimeError, ValueError) as e:
            ap.error(str(e))
        print(f"[*] {'已锁定' if created else '复用'}批次计划：{plan_path}")
        if a.batch_number > len(batches):
            ap.error(f"批次不存在：共 {len(batches)} 批，收到第 {a.batch_number} 批")
        selected = batches[a.batch_number - 1]
        selected_include = [item["path"] for item in selected]
        target = os.path.join(a.out, f"batch-{a.batch_number:03d}")
        total = sum(item["size"] for item in selected)
        n = len(selected)
        print(f"[*] 离线分批：共 {len(batches)} 批；本次第 {a.batch_number} 批，"
              f"{n} 个文件，{human(total)}")
        oversized = [item for item in selected if item["size"] > batch_bytes]
        for item in oversized:
            print(f"[!] 单文件 {item['path']} 为 {human(item['size'])}，超过批次上限，已单独成批")
        info = (total, n)
    else:
        info = expected_total(a.model, include=a.include, exclude=(exclude or None),
                              revision=a.revision, token=a.token)

    if info:
        total, n = info
        print(f"[*] 清单：{n} 个文件，共 {human(total)}")
        free = free_disk(target)
        need = total * 2 if a.tar else total  # --tar 还要一份同等空间
        if batches is not None:
            need = max(0, total - dir_size(target))
        if free is not None and free < need:
            print(f"[!] 磁盘可能不够：需约 {human(need)}"
                  f"{'（含打包）' if a.tar else ''}，剩 {human(free)} — 继续尝试…")
    download(a.model, target, revision=a.revision, include=selected_include,
             exclude=(exclude or None), token=a.token, retries=a.retries)
    if batches is not None:
        write_offline_batch_artifacts(
            a.out, target, a.model, a.revision, batches, a.batch_number,
            batch_bytes)
    if a.tar:
        make_archive(target)


def _self_cmd(cli_args):
    """以 CLI 模式再跑一份自己（GUI 的下载子进程）。

    子进程可被 kill → 这是 GUI「停止下载」的实现基础（snapshot_download
    是阻塞库调用，线程内无法中途取消；.incomplete 文件保留，重下即续传）。
    """
    if getattr(sys, "frozen", False):  # pyinstaller exe
        return [sys.executable] + cli_args
    return [sys.executable, os.path.abspath(__file__)] + cli_args


_TQDM_NOISE = None  # 延迟编译的正则（GUI 才用得到）


def _clean_child_line(line):
    """清洗下载子进程的输出行：去终端控制符；tqdm 进度条行直接丢弃。

    tqdm 的多行进度条靠 \\r 和 ESC[A（光标上移）原地重画，GUI 文本框不认，
    显示成「□ [A 1%|…」刷屏（真机实测）。总进度父进程自己算，这些行没价值。
    返回 None 表示该丢。
    """
    global _TQDM_NOISE
    import re
    if _TQDM_NOISE is None:
        _TQDM_NOISE = (re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|[\r\x08]"),
                       re.compile(r"\d+%\||\d+(\.\d+)?[KMG]?B?/s\]|\[A\b"))
    esc_re, bar_re = _TQDM_NOISE
    line = esc_re.sub("", line).rstrip()
    if not line or bar_re.search(line):
        return None
    return line


def _spawn_downloader(cli_args):
    """起下载子进程：stdout/stderr 合流、UTF-8、关 tqdm、Windows 下不弹黑窗。"""
    import subprocess
    # TQDM_DISABLE：新版 tqdm 认这个环境变量；老版不认也没事，父进程还有行过滤
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1",
               TQDM_DISABLE="1")
    if getattr(sys, "frozen", False):
        # PyInstaller 6.9+ 默认让同一 one-file EXE 的子进程复用父进程解包目录。
        # GUI 把子进程当独立 CLI 实例使用，强制重新解包可避免父目录失效后
        # 子进程在 pyi_rth__tkinter 阶段找不到 _tcl_data。
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return subprocess.Popen(
        _self_cmd(cli_args),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        encoding="utf-8", errors="replace", env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _run_self_spawn_smoke(cli_args):
    """CI 专用：让 frozen 父 EXE 走与 GUI 相同的子进程启动链路。"""
    proc = _spawn_downloader(cli_args)
    for line in proc.stdout:
        print(line, end="")
    return proc.wait()


# ───────────────────────────── GUI ─────────────────────────────
def run_gui():
    import queue
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, scrolledtext

    q = queue.Queue()  # worker → UI 线程安全通道
    root = tk.Tk()
    root.title(f"{APP_TITLE} v{APP_VERSION}")
    root.geometry("760x610")

    frm = ttk.Frame(root, padding=10)
    frm.pack(fill="both", expand=True)

    ttk.Label(frm, text="模型 id（ModelScope）").grid(row=0, column=0, sticky="w")
    model_var = tk.StringVar()
    model_box = ttk.Combobox(frm, textvariable=model_var, width=60,
                             values=[p[0] for p in PRESETS])
    model_box.grid(row=1, column=0, columnspan=2, sticky="we", pady=(0, 2))
    ttk.Label(frm, text="（可下拉选常用，或直接粘贴；例 " +
              " / ".join(p[0] for p in PRESETS[:1]) + "）",
              foreground="#666").grid(row=2, column=0, columnspan=2, sticky="w")

    ttk.Label(frm, text="保存到文件夹").grid(row=3, column=0, sticky="w", pady=(8, 0))
    out_var = tk.StringVar()
    out_entry = ttk.Entry(frm, textvariable=out_var, width=58)
    out_entry.grid(row=4, column=0, sticky="we", pady=(0, 2))

    def browse():
        d = filedialog.askdirectory()
        if d:
            out_var.set(d)

    ttk.Button(frm, text="浏览…", command=browse).grid(row=4, column=1, sticky="w", padx=(6, 0))

    skip_media_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(frm, text="跳过图片/视频等演示文件（推理用不到，更快更省盘）",
                    variable=skip_media_var).grid(row=5, column=0, columnspan=2,
                                                   sticky="w", pady=(6, 0))

    batch_var = tk.BooleanVar(value=False)
    batch_size_var = tk.StringVar(value="100")
    batch_number_var = tk.StringVar(value="1")
    batch_plan_var = tk.StringVar(value="关闭；普通模式会下载完整模型")
    batch_frame = ttk.Frame(frm)
    batch_frame.grid(row=6, column=0, columnspan=2, sticky="we", pady=(4, 0))
    batch_check = ttk.Checkbutton(batch_frame, text="离线分批下载", variable=batch_var)
    batch_check.pack(side="left")
    ttk.Label(batch_frame, text="每批上限(GB)").pack(side="left", padx=(12, 3))
    batch_size_entry = ttk.Entry(batch_frame, textvariable=batch_size_var, width=8)
    batch_size_entry.pack(side="left")
    ttk.Label(batch_frame, text="下载第").pack(side="left", padx=(12, 3))
    batch_number_entry = ttk.Entry(batch_frame, textvariable=batch_number_var, width=5)
    batch_number_entry.pack(side="left")
    ttk.Label(batch_frame, text="批（完整文件分组，不切割）").pack(side="left", padx=(3, 0))

    def update_batch_controls():
        entry_state = "normal" if batch_var.get() else "disabled"
        batch_size_entry.config(state=entry_state)
        batch_number_entry.config(state=entry_state)
        batch_plan_var.set("已启用；点下载后自动计算总批数" if batch_var.get()
                           else "关闭；普通模式会下载完整模型")

    batch_check.config(command=update_batch_controls)
    update_batch_controls()
    ttk.Label(frm, textvariable=batch_plan_var, foreground="#666").grid(
        row=7, column=0, columnspan=2, sticky="w")

    progress_bar = ttk.Progressbar(frm, maximum=1000)
    progress_bar.grid(row=8, column=0, columnspan=2, sticky="we", pady=(8, 2))

    status_var = tk.StringVar(value="就绪")
    status = ttk.Label(frm, textvariable=status_var, foreground="#0a0")
    status.grid(row=9, column=0, columnspan=2, sticky="w", pady=(0, 4))

    log_widget = scrolledtext.ScrolledText(frm, height=16, wrap="word")
    log_widget.grid(row=11, column=0, columnspan=2, sticky="nsew")
    frm.rowconfigure(11, weight=1)
    frm.columnconfigure(0, weight=1)

    about = ttk.Label(frm, text=f"v{APP_VERSION} · 作者 {APP_AUTHOR} · {APP_URL}（点击打开，问题/建议提 Issue）",
                      foreground="#06c", cursor="hand2")
    about.grid(row=12, column=0, columnspan=2, sticky="w", pady=(4, 0))

    def open_repo(_event=None):
        import webbrowser
        try:
            webbrowser.open(APP_URL)
        except Exception:  # noqa: BLE001 — 打不开浏览器就算了，地址就在字面上
            pass

    about.bind("<Button-1>", open_repo)

    def log_ui(text):
        log_widget.insert("end", text if text.endswith("\n") else text + "\n")
        log_widget.see("end")

    # 下载子进程状态（run_gui 闭包内共享；tkinter 单线程 UI，poll() 里统一消费）
    state = {"proc": None, "stopped": False, "total": None,
             "batch": False, "batch_number": None, "total_batches": None,
             "model_root": None}

    def do_download():
        model = model_var.get().strip()
        out = out_var.get().strip()
        if not model or not out:
            messagebox.showwarning(APP_TITLE, "请填模型 id 和保存文件夹")
            return
        # 模型 id 落到目标的子目录（避免直接下到选中目录根，便于多模型）
        model_root = os.path.join(out, model.split("/")[-1])
        batch_enabled = batch_var.get()
        batch_size_text = batch_size_var.get().strip()
        batch_number_text = batch_number_var.get().strip()
        if batch_enabled:
            try:
                batch_size_gb = float(batch_size_text)
                batch_number = int(batch_number_text)
                batch_bytes_from_gb(batch_size_gb)
                if batch_number < 1:
                    raise ValueError
            except ValueError:
                messagebox.showwarning(APP_TITLE, "每批上限必须大于 0，批次必须是从 1 开始的整数")
                return
            target = os.path.join(model_root, f"batch-{batch_number:03d}")
        else:
            batch_size_gb, batch_number = None, None
            target = model_root
        exclude = MEDIA_EXCLUDE if skip_media_var.get() else None
        dl_btn.config(state="disabled")
        stop_btn.config(state="normal")
        state["stopped"] = False
        state["total"] = None
        state["batch"] = batch_enabled
        state["batch_number"] = batch_number
        state["total_batches"] = None
        state["model_root"] = model_root
        progress_bar.config(value=0)
        status_var.set("查询模型清单…")
        status.config(foreground="#0a0")
        batch_plan_var.set("正在计算远端文件清单和批次…" if batch_enabled
                           else "关闭；普通模式会下载完整模型")

        def worker():
            # 1) 清单：总大小（百分比/ETA 用）+ 磁盘预检
            args = ["--model", model, "--out", model_root if batch_enabled else target]
            if batch_enabled:
                batch_bytes = batch_bytes_from_gb(batch_size_gb)
                try:
                    batches, plan_path, created = load_or_create_batch_plan(
                        model_root, model, None, None, exclude, batch_bytes)
                except (RuntimeError, ValueError) as e:
                    q.put(("__DONE__", False, e, target))
                    return
                q.put(f"[*] {'已锁定' if created else '复用'}批次计划：{plan_path}\n")
                if batch_number > len(batches):
                    q.put(("__DONE__", False,
                           ValueError(f"批次不存在：共 {len(batches)} 批，收到第 {batch_number} 批"),
                           target))
                    return
                selected = batches[batch_number - 1]
                total = sum(item["size"] for item in selected)
                n = len(selected)
                info = (total, n)
                q.put(("__BATCH_PLAN__", len(batches), batch_number, total, n))
                args += ["--batch-size-gb", batch_size_text,
                         "--batch-number", str(batch_number)]
            else:
                info = expected_total(model, exclude=exclude)
            if info:
                total, n = info
                q.put(("__TOTAL__", total))
                label = "本批" if batch_enabled else "清单"
                q.put(f"[*] {label}：{n} 个文件，共 {human(total)}\n")
                free = free_disk(target)
                need = max(0, total - dir_size(target)) if batch_enabled else total
                if free is not None and free < need:
                    q.put(f"[!] 注意：磁盘剩 {human(free)}，不够 {human(need)}，"
                          f"大概率会下到一半失败！建议停止并换大盘。\n")
            else:
                q.put("[!] 查不到模型清单（不影响下载，只是不显示百分比）\n")

            # 清单查询期间用户可能已点「停止」
            if state["stopped"]:
                q.put(("__STOPPED__", target))
                return

            # 2) 起下载子进程（可被「停止」kill；.incomplete 保留 → 重下即续传）
            if exclude:
                args += ["--skip-media"]
            try:
                proc = _spawn_downloader(args)
            except Exception as e:  # noqa: BLE001
                q.put(("__DONE__", False, e, target))
                return
            state["proc"] = proc
            q.put(("__STARTED__", target))

            # 3) 转发子进程输出到日志框（tqdm 进度条行等噪音直接丢）
            tail = []
            for line in proc.stdout:
                line = _clean_child_line(line.rstrip("\n"))
                if line:
                    tail = (tail + [line])[-8:]
                    if "正在生成第" in line and "SHA256" in line:
                        q.put(("__HASHING__", line))
                    q.put(line + "\n")
            rc = proc.wait()
            state["proc"] = None
            if state["stopped"]:
                q.put(("__STOPPED__", target))
            else:
                err = None if rc == 0 else RuntimeError(
                    "\n".join(tail) or f"下载进程退出码 {rc}")
                q.put(("__DONE__", rc == 0, err, target))

        def progresspoll():
            # 父进程直接量目标目录（.incomplete 也在里面）→ 速度/百分比/ETA
            prev_bytes, prev_t, speed = None, None, 0.0
            while True:
                time.sleep(1.0)
                p = state["proc"]
                if p is None or p.poll() is not None:
                    break
                cur = dir_size(target)
                now = time.monotonic()
                if prev_bytes is not None and now > prev_t:
                    inst = max(0.0, (cur - prev_bytes) / (now - prev_t))
                    speed = inst if speed == 0 else 0.7 * speed + 0.3 * inst
                prev_bytes, prev_t = cur, now
                q.put(("__PROG__", cur, speed))

        def start_polling(*_):
            threading.Thread(target=progresspoll, daemon=True).start()

        state["on_started"] = start_polling
        threading.Thread(target=worker, daemon=True).start()

    def do_stop():
        state["stopped"] = True  # proc 未起（还在查清单）也生效：worker 会检查
        stop_btn.config(state="disabled")
        p = state["proc"]
        if p is not None:
            try:
                p.kill()
            except Exception:  # noqa: BLE001
                pass

    def start_tar(target):
        """下完后弹问要不要打 tar；点「是」走这里（worker 线程，免冻 UI）。"""
        dl_btn.config(state="disabled")
        status_var.set("打包中…（大模型需数分钟，完成会弹窗）")

        def worker():
            ok, err, tarp = True, None, None
            try:
                tarp = make_archive(target, log=lambda m: q.put(m + "\n"))
            except Exception as e:  # noqa: BLE001
                ok, err = False, e
            q.put(("__TARDONE__", ok, err, tarp))

        threading.Thread(target=worker, daemon=True).start()

    dl_btn = ttk.Button(frm, text="下载 / Download", command=do_download)
    dl_btn.grid(row=10, column=0, sticky="we", pady=(0, 6))
    stop_btn = ttk.Button(frm, text="停止", command=do_stop, state="disabled")
    stop_btn.grid(row=10, column=1, sticky="we", padx=(6, 0), pady=(0, 6))

    def poll():
        import queue as _q
        try:
            while True:
                item = q.get_nowait()
                if isinstance(item, tuple) and item and item[0] == "__TOTAL__":
                    state["total"] = item[1]
                elif isinstance(item, tuple) and item and item[0] == "__BATCH_PLAN__":
                    _, total_batches, batch_number, total, n = item
                    state["total_batches"] = total_batches
                    batch_plan_var.set(
                        f"共 {total_batches} 批；当前第 {batch_number} 批："
                        f"{n} 个完整文件，{human(total)}")
                elif isinstance(item, tuple) and item and item[0] == "__STARTED__":
                    status_var.set("下载中…（可最小化；「停止」后重下即续传）")
                    if state.get("on_started"):
                        state["on_started"]()
                elif isinstance(item, tuple) and item and item[0] == "__HASHING__":
                    status_var.set("下载完成，正在生成本批 SHA256 校验清单…")
                elif isinstance(item, tuple) and item and item[0] == "__PROG__":
                    _, cur, speed = item
                    total = state["total"]
                    txt = f"已下载 {human(cur)}"
                    if total:
                        pct = min(100.0, cur * 100.0 / total)
                        progress_bar.config(value=pct * 10)
                        txt += f" / {human(total)}（{pct:.1f}%）"
                        if speed > 1:
                            remain = max(0, total - cur) / speed
                            m, s = divmod(int(remain), 60)
                            h, m = divmod(m, 60)
                            eta = f"{h}小时{m:02d}分" if h else (f"{m}分{s:02d}秒" if m else f"{s}秒")
                            txt += f"  剩余约 {eta}"
                    if speed > 1:
                        txt += f"  —  {human(speed)}/s"
                    status_var.set(txt)
                elif isinstance(item, tuple) and item and item[0] == "__STOPPED__":
                    _, target = item
                    dl_btn.config(state="normal")
                    stop_btn.config(state="disabled")
                    status_var.set("已停止 — 再点「下载」从断点继续")
                    status.config(foreground="#c60")
                    log_ui(f"[!] 已停止。已下载的部分保留在 {target}，重下同一模型即续传。")
                    # 不打算继续了？可当场取消（删掉已下载部分腾盘）
                    got = dir_size(target) if os.path.isdir(target) else 0
                    if got > 0 and messagebox.askyesno(
                            APP_TITLE,
                            f"已停止。已下载 {human(got)} 保留在：\n{target}\n\n"
                            f"以后还要继续下这个模型吗？\n"
                            f"「是」= 保留（下次点下载从断点继续）\n"
                            f"「否」= 取消本次下载，删除已下载的部分腾出磁盘") is False:

                        def cleaner(path=target):
                            import shutil
                            try:
                                shutil.rmtree(path)
                                q.put(f"[ok] 已删除 {path}\n")
                            except Exception as e:  # noqa: BLE001
                                q.put(f"[x] 删除失败：{e}\n")

                        status_var.set("已取消，正在删除已下载的部分…")
                        threading.Thread(target=cleaner, daemon=True).start()
                elif isinstance(item, tuple) and item and item[0] == "__DONE__":
                    _, ok, err, target = item
                    dl_btn.config(state="normal")
                    stop_btn.config(state="disabled")
                    if ok:
                        progress_bar.config(value=1000)
                        status.config(foreground="#0a0")
                        if state["batch"]:
                            batch_number = state["batch_number"]
                            total_batches = state["total_batches"]
                            guide = os.path.join(
                                state["model_root"], "_OFFLINE-SERVER-INSTRUCTIONS.txt")
                            status_var.set(f"第 {batch_number}/{total_batches} 批完成 ✓")
                            log_ui(f"[ok] 本批可搬运：{target}")
                            log_ui(f"[i] 服务器命令说明：{guide}")
                            if batch_number < total_batches:
                                batch_number_var.set(str(batch_number + 1))
                                next_hint = f"界面已切到第 {batch_number + 1} 批；本批上传并校验后再继续。"
                            else:
                                next_hint = "这是最后一批；全部上传后按说明执行总校验。"
                            messagebox.showinfo(
                                APP_TITLE,
                                f"第 {batch_number}/{total_batches} 批完成：\n{target}\n\n"
                                f"已生成 SHA256、校验脚本和服务器命令。\n"
                                f"{next_hint}\n\n"
                                f"服务器校验通过前不要删除本批。")
                        else:
                            status_var.set("完成 ✓")
                            if messagebox.askyesno(
                                    APP_TITLE,
                                    f"下载完成：\n{target}\n\n"
                                    f"现在打包成 .tar（带校验码）便于传到部署机吗？\n"
                                    f"需额外同等磁盘空间；选「否」可稍后手动打包。"):
                                start_tar(target)
                            else:
                                b, p = os.path.basename(target), os.path.dirname(target)
                                log_ui(f"如需手动打包：tar -cf \"{b}.tar\" -C \"{p}\" \"{b}\"")
                    else:
                        status_var.set("失败 ✗")
                        status.config(foreground="#c00")
                        messagebox.showerror(
                            APP_TITLE,
                            f"下载失败：\n{err}\n\n断网/中断后，重新点 Download 即续传。")
                elif isinstance(item, tuple) and item and item[0] == "__TARDONE__":
                    _, ok, err, tarp = item
                    dl_btn.config(state="normal")
                    if ok:
                        status_var.set("打包完成 ✓")
                        status.config(foreground="#0a0")
                        messagebox.showinfo(
                            APP_TITLE,
                            f"打包完成：\n{tarp}\n{tarp}.sha256\n\n"
                            f"把这两个文件一起拷到部署机，再核对校验码即可。")
                    else:
                        status_var.set("打包失败 ✗")
                        status.config(foreground="#c00")
                        messagebox.showerror(APP_TITLE, f"打包失败：\n{err}")
                else:
                    log_ui(str(item).rstrip("\n"))
        except _q.Empty:
            pass
        root.after(150, poll)

    def on_close():
        p = state["proc"]
        if p is not None and p.poll() is None:
            if not messagebox.askokcancel(
                    APP_TITLE, "正在下载。关闭会停止下载（已下载部分保留，"
                    "下次重下同一模型即续传）。确定关闭？"):
                return
            state["stopped"] = True
            try:
                p.kill()
            except Exception:  # noqa: BLE001
                pass
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    log_ui(f"{APP_TITLE} v{APP_VERSION} — 填模型 id、选文件夹、点下载。")
    log_ui("常用：" + "  ".join(f"{i}={d}" for i, (m, d) in zip([p[0] for p in PRESETS], PRESETS)))
    root.after(150, poll)
    root.mainloop()


def main():
    _harden_stdio()
    if len(sys.argv) > 1 and sys.argv[1] == "--_self-spawn-smoke":
        if len(sys.argv) == 2:
            print("[x] --_self-spawn-smoke 缺少子进程参数", file=sys.stderr)
            sys.exit(2)
        sys.exit(_run_self_spawn_smoke(sys.argv[2:]))
    # 有参数 → CLI；无参数（双击 exe）→ GUI
    if len(sys.argv) > 1:
        run_cli(sys.argv[1:])
    else:
        try:
            run_gui()
        except Exception as e:  # noqa: BLE001 — 无显示环境(如纯命令行 Linux)兜底
            print(f"[x] 无法启动 GUI：{e}\n请用命令行：python app.py --model <id> --out <dir>",
                  file=sys.stderr)
            sys.exit(2)


if __name__ == "__main__":
    main()
