@echo off
rem Drag one or more .dxf files onto this file. It asks for the final printed width,
rem then writes <name>_clean.dxf and <name>_review.dxf next to each input.
if "%~1"=="" (
    echo Drag one or more .dxf files onto this file to clean them.
    pause
    exit /b
)
where py >nul 2>nul
if %errorlevel%==0 (
    py "%~dp0LineDensityCleanUp_dxf.py" %*
) else (
    python "%~dp0LineDensityCleanUp_dxf.py" %*
)
pause
