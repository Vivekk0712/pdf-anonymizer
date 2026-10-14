@echo off
title PDF Anonymizer Launcher
echo ===================================================
echo Starting Bulk PDF Anonymizer...
echo ===================================================

:: Navigate to the directory where this script is located
cd /d "%~dp0"

:: Activate virtual environment if present
if exist "venv\Scripts\activate.bat" (
    echo Activating Python 3.12 virtual environment (venv)...
    call "venv\Scripts\activate.bat"
) else (
    echo No local venv found, using system Python...
)

:: Launch the Streamlit application
echo Launching Streamlit web application...
streamlit run app.py

:: Keep window open if the app stops or encounters an error
pause
