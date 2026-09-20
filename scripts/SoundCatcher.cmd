@echo off
REM SoundCatcher GUI 启动器（无黑窗）。
REM
REM 为什么需要这个：`soundcatcher-gui.exe` 是 console 脚本包装器，
REM 双击会弹一个黑窗常驻。改用 pythonw.exe 执行同一入口即无窗口。
REM
REM 本文件用 **相对路径** 定位工程根（%~dp0 是本 .cmd 所在目录），
REM 因此整个工程目录可以整体搬走而不用改这个文件。
setlocal
set "ROOT=%~dp0.."
set "PYW=%ROOT%\.venv\Scripts\pythonw.exe"
if not exist "%PYW%" (
  echo [SoundCatcher] 找不到虚拟环境：%PYW%
  echo 请先在工程目录执行： python -m venv .venv ^&^& .venv\Scripts\pip install -e .
  pause
  exit /b 1
)
set "PYTHONPATH=%ROOT%\src;%PYTHONPATH%"
start "" "%PYW%" -m soundcatcher.gui.app
endlocal
