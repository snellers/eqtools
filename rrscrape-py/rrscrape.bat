@echo off
REM This is a launcher script for use on Windows. 
REM It checks that uv is installed then runs the script in a python virtual environment.
where /q uv
if errorlevel 1 (
    winget install --id=astral-sh.uv  -e
)
uv run .\rrscrape.py
