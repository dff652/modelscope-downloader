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
APP_VERSION = "0.2.0"

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


def dir_size(p):
    total = 0
    for root, _, files in os.walk(p):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


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
                                 description="ModelScope 模型下载（断点续传）")
    ap.add_argument("--model", required=True, help="模型 id，如 Qwen/Qwen3-0.6B")
    ap.add_argument("--out", required=True, help="本地目标目录（建议短路径）")
    ap.add_argument("--include", nargs="*", default=None, help="只下匹配 glob")
    ap.add_argument("--exclude", nargs="*", default=None, help="跳过匹配 glob")
    ap.add_argument("--revision", default=None, help="版本/分支")
    ap.add_argument("--token", default=None, help="受限模型才需要")
    ap.add_argument("--retries", type=int, default=20)
    ap.add_argument("--skip-media", action="store_true",
                    help="跳过图片/视频/音频等演示文件（推理用不到，更快更省盘）")
    ap.add_argument("--tar", action="store_true",
                    help="下完自动打包成 .tar + .sha256（便于传 air-gapped 机）")
    a = ap.parse_args(argv)
    exclude = list(a.exclude) if a.exclude else []
    if a.skip_media:
        exclude += MEDIA_EXCLUDE
    download(a.model, a.out, revision=a.revision, include=a.include,
             exclude=(exclude or None), token=a.token, retries=a.retries)
    if a.tar:
        make_archive(a.out)


# ───────────────────────────── GUI ─────────────────────────────
def run_gui():
    import queue
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, scrolledtext

    q = queue.Queue()  # worker → UI 线程安全通道
    root = tk.Tk()
    root.title(f"{APP_TITLE} v{APP_VERSION}")
    root.geometry("720x500")

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

    status_var = tk.StringVar(value="就绪")
    status = ttk.Label(frm, textvariable=status_var, foreground="#0a0")
    status.grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 4))

    log_widget = scrolledtext.ScrolledText(frm, height=16, wrap="word")
    log_widget.grid(row=8, column=0, columnspan=2, sticky="nsew")
    frm.rowconfigure(8, weight=1)
    frm.columnconfigure(0, weight=1)

    def log_ui(text):
        log_widget.insert("end", text if text.endswith("\n") else text + "\n")
        log_widget.see("end")

    def do_download():
        model = model_var.get().strip()
        out = out_var.get().strip()
        if not model or not out:
            messagebox.showwarning(APP_TITLE, "请填模型 id 和保存文件夹")
            return
        # 模型 id 落到目标的子目录（避免直接下到选中目录根，便于多模型）
        target = os.path.join(out, model.split("/")[-1])
        exclude = MEDIA_EXCLUDE if skip_media_var.get() else None
        dl_btn.config(state="disabled")
        status_var.set("下载中…（可最小化，完成会弹窗）")

        def worker():
            stop = threading.Event()

            def sizepoll():
                while not stop.is_set():
                    try:
                        q.put(f"    已下载 {human(dir_size(target))}\n")
                    except Exception:  # noqa: BLE001
                        pass
                    stop.wait(2.0)

            threading.Thread(target=sizepoll, daemon=True).start()
            ok, err = True, None
            try:
                download(model, target, exclude=exclude, log=lambda m: q.put(m + "\n"))
            except Exception as e:  # noqa: BLE001
                ok, err = False, e
            finally:
                stop.set()
            q.put(("__DONE__", ok, err, target))

        threading.Thread(target=worker, daemon=True).start()

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
    dl_btn.grid(row=7, column=0, columnspan=2, sticky="we", pady=(0, 6))

    def poll():
        import queue as _q
        try:
            while True:
                item = q.get_nowait()
                if isinstance(item, tuple) and item and item[0] == "__DONE__":
                    _, ok, err, target = item
                    dl_btn.config(state="normal")
                    if ok:
                        status_var.set("完成 ✓")
                        status.config(foreground="#0a0")
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

    log_ui(f"{APP_TITLE} v{APP_VERSION} — 填模型 id、选文件夹、点下载。")
    log_ui("常用：" + "  ".join(f"{i}={d}" for i, (m, d) in zip([p[0] for p in PRESETS], PRESETS)))
    root.after(150, poll)
    root.mainloop()


def main():
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
