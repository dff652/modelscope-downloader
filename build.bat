@echo off
REM ============================================================
REM  Build single-file Windows .exe  (run this ON Windows)
REM  Output: dist\ModelScopeDownloader.exe  (double-click -> GUI)
REM ============================================================
setlocal
chcp 65001 >nul 2>nul

where python >nul 2>nul
if errorlevel 1 (
  echo [x] Python not found. Install Python 3.10+ from python.org ^(check "Add Python to PATH"^), then re-run.
  pause & exit /b 1
)

echo [*] Installing build deps ^(pyinstaller + modelscope^) ...
python -m pip install -U pyinstaller modelscope
if errorlevel 1 ( echo [x] pip install failed & pause & exit /b 1 )

echo [*] Building exe ...
REM --windowed = no console (GUI app); --onefile = single exe;
REM --collect-all modelscope = bundle modelscope's dynamic submodules/data (else missing-module at runtime)
pyinstaller --onefile --windowed --name ModelScopeDownloader --collect-all modelscope app.py
if errorlevel 1 ( echo [x] pyinstaller failed & pause & exit /b 1 )

echo.
echo [done] dist\ModelScopeDownloader.exe
echo        Double-click it to open the GUI. First launch may be slow (unpacking).
pause
