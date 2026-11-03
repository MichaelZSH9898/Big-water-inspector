@echo off
cd /d "%~dp0\.."
start "" pythonw -m settings_ui.app --tab overtime_care --close-after 25
