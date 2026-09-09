@echo off
cd /d "%~dp0"
py backend\snapshot\gacd_playwright_catalog.py --chrome
pause
