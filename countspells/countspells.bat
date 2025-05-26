@echo off
REM This is a launcher script for use on Windows. 
REM It checks that the python virtual environment is configured and up to date before running the python script.
REM Install 'uv' if it's missing
where /q uv
if errorlevel 1 (
    winget install --id=astral-sh.uv  -e
)
REM Create the python virtual environment for the project if it's missing
if not exist .venv (
    uv venv
    call .venv\Scripts\activate
    uv pip install -r pyproject.toml
    call deactivate
)
REM Run using the project's virtual environment
call .venv\Scripts\activate.bat
uv sync -q
python countspells.py
call deactivate
