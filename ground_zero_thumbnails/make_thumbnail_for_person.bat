@echo off
REM Double click: type a person and a title; it finds a freely licensed photo and makes the thumbnail.
cd /d "%~dp0"
if not exist ".venv\Scripts\activate.bat" (
  echo Could not find .venv in this folder. Run the setup steps in README.md first.
  pause
  exit /b 1
)
set /p PERSON=Person (for example Aliko Dangote): 
set /p TITLE=Title for the thumbnail: 
call ".venv\Scripts\activate.bat"
python thumbnail.py "%TITLE%" --person "%PERSON%"
if not errorlevel 1 start "" .
pause
