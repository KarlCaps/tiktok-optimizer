@echo off
REM Drag and drop one or more video files onto this file to optimize them.
REM Uses the 1080p preset. Edit the line below to change options.

if "%~1"=="" (
    echo Drag and drop a video file onto this script.
    pause
    exit /b
)

python "%~dp0tiktok_optimizer.py" %* --preset 1080p
pause
