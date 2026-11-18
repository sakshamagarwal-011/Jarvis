@echo off
cd /d "%~dp0"
echo Starting JARVIS...
call .venv\Scripts\activate.bat
".venv\Scripts\python.exe" main.py
if errorlevel 1 pause

