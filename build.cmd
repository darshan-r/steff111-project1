@echo off
rem This script runs PyInstaller and copies the output

rem Set the path to your virtual environment
set "venv_path=venv"

rem Activate the virtual environment
call "%venv_path%\Scripts\activate.bat"


rem Run PyInstaller with the specified spec file
pyinstaller main.spec

rem Check if the build was successful
if %ERRORLEVEL% neq 0 (
    echo PyInstaller build failed. Exiting.
    exit /b %ERRORLEVEL%
)

rem Define the source and destination paths
set "source=dist\main"
set "destination=."

rem Check if the source directory exists
if not exist "%source%" (
    echo Source directory "%source%" does not exist. Exiting.
    exit /b 1
)

rem Copy the output directory to the current directory
xcopy /e /i "%source%" "%destination%"

rem Check if the copy was successful
if %ERRORLEVEL% neq 0 (
    echo Copying failed. Exiting.
    exit /b %ERRORLEVEL%
)

echo Build and copy completed successfully.
