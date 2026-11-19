@echo off
REM Drag an audio file here: lists every pause it would shorten and writes a preview .tightened.wav to listen to. No video.
cd /d "%~dp0"
if "%~1"=="" (
  echo Drag an audio file onto this file to use it.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\activate.bat" (
  echo Could not find .venv in this folder.
  pause
  exit /b 1
)
call ".venv\Scripts\activate.bat"
python render.py "%~1" --pauses report
if not errorlevel 1 start "" "%~dpn1.tightened.wav"
pause
