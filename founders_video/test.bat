@echo off
REM Double click to render clip.mp3 (in this folder) with the current render.py
cd /d "%~dp0"
if not exist ".venv\Scripts\activate.bat" (
  echo Could not find .venv in this folder. Put test.bat next to render.py and .venv.
  pause
  exit /b 1
)
if not exist "clip.mp3" (
  echo Could not find clip.mp3 in this folder.
  pause
  exit /b 1
)
call ".venv\Scripts\activate.bat"
python render.py clip.mp3 %*
if not errorlevel 1 start "" "output.mp4"
pause
