@echo off
cd /d "%~dp0"
title THSC Paper Extractor
python thsc_extractor.py %*
echo.
pause
