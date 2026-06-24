@echo off
REM ============================================================
REM  Build single-file Windows .exe  (run this ON Windows)
REM  Output: dist\ModelScopeDownloader.exe  (double-click -> GUI)
REM  Save this file as UTF-8 WITHOUT BOM (BOM corrupts line 1).
REM ============================================================
setlocal
chcp 65001 >nul 2>nul

REM Anchor to this script's own folder, even if double-clicked from elsewhere
REM (a double-click may start in System32 / the user profile, not here).
cd /d "%~dp0"

REM All output (this script + every command) is tee'd into build.log so a
REM failed run can be sent to a developer.  Log path is shown on any failure.
set "LOG=%~dp0build.log"

REM Fresh log each run, with a header so a forwarded log is self-describing.
> "%LOG%" echo === ModelScopeDownloader build started %DATE% %TIME% ===

echo ============================================================
echo  ModelScope Downloader - build exe  (Windows)
echo  日志 / log: "%LOG%"
echo ============================================================
echo.

REM ---- 0) locate python ----------------------------------------------------
where python >>"%LOG%" 2>&1
if errorlevel 1 (
  echo [x] Python not found.  未找到 Python.
  echo     Install 64-bit Python 3.11 from python.org
  echo     安装 64 位 Python 3.11^(python.org^), 勾选 "Add Python to PATH", 再重跑.
  echo [x] Python not found >>"%LOG%"
  goto :fail
)

REM ---- 1) verify python is a REAL 64-bit install (not the MS Store stub) ----
echo [*] Environment / 环境:
echo -------------------------------------------- >>"%LOG%"

set "PYPATH="
for /f "delims=" %%p in ('where python 2^>nul') do if not defined PYPATH set "PYPATH=%%p"
echo     python path: %PYPATH%
echo python path: %PYPATH% >>"%LOG%" 2>&1

REM A real Python prints "Python 3.x.y".  The Microsoft Store python.exe ALIAS
REM (under ...\WindowsApps\) prints NOTHING and just opens the Store -- catch it.
set "PYVER="
for /f "delims=" %%v in ('python --version 2^>^&1') do if not defined PYVER set "PYVER=%%v"
if not defined PYVER (
  echo     python --version: ^(no output^)
  echo python --version: ^(no output^) >>"%LOG%"
  echo.
  echo [x] `python` returned no version.  python 没有返回版本号.
  echo     Almost certainly the Microsoft Store "python.exe" ALIAS stub,
  echo     NOT a real Python install.  path: %PYPATH%
  echo     这其实是微软商店的 python.exe 别名占位, 不是真的 Python.
  echo     ----- FIX / 解决 -----
  echo      1^) Install 64-bit Python 3.11 from python.org; check "Add Python to PATH".
  echo         装 64 位 Python 3.11^(python.org^), 勾选 "Add Python to PATH".
  echo      2^) Turn OFF the Store alias: Settings ^> Apps ^> Advanced app settings ^>
  echo         App execution aliases ^> turn OFF python.exe AND python3.exe.
  echo         关闭商店别名: 设置 ^> 应用 ^> 高级应用设置 ^> 应用执行别名 ^> 关掉 python.exe / python3.exe.
  echo      3^) Open a NEW cmd window so PATH refreshes, then re-run build.bat.
  echo         开个新命令行窗口^(刷新 PATH^)再重跑 build.bat.
  echo [x] python --version empty - likely MS Store alias stub >>"%LOG%"
  goto :fail
)
echo     python --version: %PYVER%
echo python --version: %PYVER% >>"%LOG%" 2>&1

echo     pip --version:
python -m pip --version
python -m pip --version >>"%LOG%" 2>&1

REM bitness GATE: require 64-bit (32-bit breaks pyinstaller/modelscope here).
for /f %%b in ('python -c "import sys;print(64 if sys.maxsize>2**32 else 32)"') do set "BITS=%%b"
echo     bitness (must be 64): %BITS%
echo bitness %BITS% >>"%LOG%" 2>&1
if not "%BITS%"=="64" (
  echo [x] Python is not 64-bit ^(got "%BITS%"^).  当前不是 64 位 Python.
  echo     Install 64-bit Python 3.11 from python.org, then re-run.
  echo     请装 64 位 Python 3.11^(python.org^)后重试.
  echo [x] not 64-bit python: "%BITS%" >>"%LOG%"
  goto :fail
)
echo -------------------------------------------- >>"%LOG%"
echo.

REM ---- 2) upgrade pip first (warn only; do NOT abort on failure) -----------
echo [*] Upgrading pip (best effort; failure here is non-fatal) ...
echo     升级 pip^(失败也继续^) ...
python -m pip install -U --no-input --disable-pip-version-check pip >>"%LOG%" 2>&1
if errorlevel 1 (
  echo [!] pip self-upgrade failed - continuing with current pip.
  echo     pip 自升级失败, 用当前版本继续. ^(详见 build.log^)
  echo [!] pip self-upgrade failed - continuing >>"%LOG%"
)
echo.

REM ============================================================
REM  IMPORTANT: install PLAIN `modelscope` (NO bracket extra).
REM  It is the lightweight hub-only package (a few MB of pure-python
REM  wheels) and is all snapshot_download needs.
REM  Do NOT add modelscope[framework]/[all]/[nlp]/[cv]/[audio] -- those pull
REM  torch/scipy/transformers (hundreds of MB to multi-GB) and can force a
REM  from-source build needing the MSVC C++ compiler the operator won't have.
REM  千万不要加 [framework]/[all]/[nlp] 等 extra, 会拉 torch/scipy 上 GB.
REM ============================================================
set "PIP=python -m pip install -U --no-input --disable-pip-version-check"
set "PKGS=pyinstaller modelscope"

REM ---- 3) install deps: default PyPI first, then Tsinghua mirror fallback --
echo [*] Installing build deps ^(pyinstaller + modelscope^) ...
echo     安装依赖中, 可能要几分钟, 期间无输出请耐心等待 ...
echo.
echo [*] Attempt 1/2: default PyPI (pypi.org)  默认源 ...
echo === pip attempt 1: default PyPI === >>"%LOG%"
%PIP% %PKGS% >>"%LOG%" 2>&1
if not errorlevel 1 goto :deps_ok

echo [!] Default PyPI failed. 默认源失败.
echo [!] Auto-retrying with 清华 Tsinghua mirror (with bigger timeout/retries) ...
echo     自动改用清华镜像重试 ...
echo === pip attempt 2: Tsinghua mirror === >>"%LOG%"
%PIP% --default-timeout 120 --retries 5 -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn %PKGS% >>"%LOG%" 2>&1
if not errorlevel 1 (
  echo [ok] Installed via Tsinghua mirror.  已用清华镜像装好.
  goto :deps_ok
)

REM ---- both attempts failed: actionable troubleshooting -------------------
echo.
echo ============================================================
echo  [x] pip install FAILED after 2 attempts.  两次安装均失败.
echo ============================================================
echo  See the FULL pip error below ^(also saved in build.log^):
echo  完整错误见下方^(并已存入 build.log^):
echo ------------------------------------------------------------
type "%LOG%"
echo ------------------------------------------------------------
echo.
echo  Common causes / 常见原因 ^& 解决:
echo.
echo  1^) Network / proxy ^(网络或代理^):
echo        - Slow/blocked link: try another mirror manually, e.g. Aliyun:
echo          换源重试, 例如阿里云:
echo          python -m pip install --default-timeout 120 --retries 5 -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com -U pyinstaller modelscope
echo        - Behind a company proxy ^(公司代理^)? set before re-running:
echo            set HTTP_PROXY=http://USER:PASS@proxyhost:port
echo            set HTTPS_PROXY=http://USER:PASS@proxyhost:port
echo          ^(URL-encode special chars; a literal %% must be doubled to %%%% here^)
echo.
echo  2^) SSL: CERTIFICATE_VERIFY_FAILED ^(公司防火墙拦 TLS / 系统时间不对^):
echo        - Check Windows date/time/timezone is correct ^(10-second fix^).
echo        - Or give pip the corporate root CA:
echo            set PIP_CERT=C:\path\to\corp-root-ca.pem
echo.
echo  3^) Disk / permission ^(磁盘或权限^):
echo        - Free up disk space, or retry as Administrator,
echo          or add --user to the pip command above.  ^(加 --user 装到用户目录^)
echo.
echo  4^) Exact manual mirror command ^(copy-paste, 手动命令^):
echo        python -m pip install --default-timeout 120 --retries 5 -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn -U pyinstaller modelscope
echo.
echo  Send build.log to the developer if stuck:  卡住请把日志发给开发:
echo        "%LOG%"
echo.
goto :fail

:deps_ok
echo [ok] Dependencies installed.  依赖已安装. ^(details in build.log^)
echo.

REM ---- 4) optional icon ---------------------------------------------------
REM Optional icon: drop an icon.ico next to this script to brand the exe.
set ICON=
if exist icon.ico set ICON=--icon icon.ico

REM ---- 5) build the exe ---------------------------------------------------
echo [*] Building exe ...  正在打包 ...
echo === pyinstaller build === >>"%LOG%"
REM --windowed = no console (GUI app); --onefile = single exe;
REM --collect-all modelscope = bundle modelscope's dynamic submodules/data + metadata
REM   (else "No module named ..." / version-lookup errors at runtime).
python -m PyInstaller --onefile --windowed --name ModelScopeDownloader --collect-all modelscope %ICON% app.py >>"%LOG%" 2>&1
if errorlevel 1 (
  echo [x] pyinstaller build failed.  打包失败. ^(full log: "%LOG%"^)
  echo     If the EXE builds but crashes at launch with "No module named X",
  echo     re-run adding flags until it opens, e.g.:
  echo        --hidden-import X            ^(one per missing module^)
  echo        --collect-all X             ^(if X also has data/dynamic imports^)
  echo        --collect-all modelscope_hub ^(if error names modelscope_hub^)
  echo        --copy-metadata modelscope  ^(if error mentions importlib.metadata / version^)
  echo     Then paste the working flags into this build.bat so the next build just works.
  echo     ----------------------------------------
  echo     Last lines of build.log:
  echo     ----------------------------------------
  type "%LOG%"
  goto :fail
)

REM ---- 6) verify the exe survived (AV may quarantine it) ------------------
if not exist "dist\ModelScopeDownloader.exe" (
  echo [x] Build reported OK but dist\ModelScopeDownloader.exe is missing.
  echo     可能被杀毒软件误删/隔离 ^(Windows Defender 等^).
  echo     PyInstaller --onefile exes are often false-positive flagged.
  echo     Check antivirus quarantine, or temporarily exclude this folder, then rebuild.
  echo [x] output exe missing after build - likely AV quarantine >>"%LOG%"
  goto :fail
)

echo.
echo === build OK %DATE% %TIME% === >>"%LOG%"
echo ============================================================
echo  [done] dist\ModelScopeDownloader.exe
echo ============================================================
echo  Double-click it to open the GUI. First launch may be slow (unpacking).
echo  双击运行; 首次启动较慢^(解包^).
echo  If Windows SmartScreen warns (unsigned exe): More info -^> Run anyway.
echo  若 SmartScreen 拦截^(未签名^): 更多信息 -^> 仍要运行.
echo  Build log: "%LOG%"
echo.
echo Press any key to close this window.
pause >nul
endlocal & exit /b 0

:fail
echo.
echo ============================================================
echo  BUILD FAILED.  构建失败. 请阅读上面的提示.
echo  Read the messages above. Log file / 日志:
echo  "%LOG%"
echo ============================================================
echo.
pause
endlocal & exit /b 1
