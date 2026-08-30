@echo off
rem Double-clickable launcher for Winnotix.
rem Delegates to build.py, which sets up anything missing before launching.
rem %~dp0 is this file's directory, so it works from any working directory.

python "%~dp0build.py" run %*

rem Pause only on failure: on a double-click the console vanishes with the
rem window, and the error message would go with it.
if errorlevel 1 (
    echo.
    echo Winnotix exited with an error ^(code %errorlevel%^).
    pause
)
