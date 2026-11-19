@echo off
REM Drag an MP3 or WAV file onto this file to render it
cd /d "%~dp0"
if "%~1"=="" (
  echo Drag an audio file onto render.bat to use it.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\activate.bat" (
  echo Could not find .venv in this folder. Put render.bat next to render.py and .venv.
  pause
  exit /b 1
)
call ".venv\Scripts\activate.bat"
python render.py "%~1"
if not errorlevel 1 start "" "%~dp1output.mp4"
pause
