@echo off
rem STELLAR prototype: double-click to start (server + Ground Control dashboard + live data).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_prototype.ps1" %*
if errorlevel 1 pause
