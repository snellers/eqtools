@echo off
REM This is an installer script for use on Windows.
REM This script ensures that 'uv' is installed and that the project has a virtual environment.
REM It should be run once before running the rrscrape script.
winget install --id=astral-sh.uv  -e
uv venv
call .venv\Scripts\activate
uv pip install -r pyproject.toml
deactivate
