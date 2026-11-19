@echo off
REM Drag a photo onto this file. It asks for the title, then makes the thumbnail.
cd /d "%~dp0"
if "%~1"=="" (
  echo Drag a photo onto make_thumbnail.bat to use it.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\activate.bat" (
  echo Could not find .venv in this folder. Run the setup steps in README.md first.
  pause
  exit /b 1
)
set /p TITLE=Title for the thumbnail: 
call ".venv\Scripts\activate.bat"
python thumbnail.py "%~1" "%TITLE%" -o "%~dpn1_thumbnail.png"
if not errorlevel 1 start "" "%~dpn1_thumbnail.png"
pause
