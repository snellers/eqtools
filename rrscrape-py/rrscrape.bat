@echo off
REM This is a launcher script for use on Windows. 
REM It checks that the python virtual environment is configured and up to date before running the python script.
where /q uv
if errorlevel 1 (
	echo The 'uv' application could not be found. Did you follow the setup steps in the README?
	exit /B
)
if not exist .venv (
	echo The '.venv' directory was not found. Did you follow the setup steps in the README?
	exit /B
)
call .venv\Scripts\activate.bat
uv sync -q
python rrscrape.py
deactivate
