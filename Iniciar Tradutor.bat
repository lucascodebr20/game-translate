@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Preparando o tradutor pela primeira vez...
  set "PYTHON_EXE=py -3"
  if exist "%LOCALAPPDATA%\Python\bin\python.exe" set "PYTHON_EXE=%LOCALAPPDATA%\Python\bin\python.exe"
  %PYTHON_EXE% -m venv .venv
  if errorlevel 1 (
    echo Nao foi possivel localizar o Python.
    pause
    exit /b 1
  )
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo Falha ao instalar as dependencias.
    pause
    exit /b 1
  )
)
start "" ".venv\Scripts\pythonw.exe" -m game_translate
