@echo off
title LyricOverLay Private Launcher
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Thư mục môi trường ảo .venv không tồn tại!
    pause
    exit /b 1
)
:: Chạy ứng dụng Python ẩn cửa sổ CMD đen bằng pythonw.exe
start "" ".venv\Scripts\pythonw.exe" "app.py"
