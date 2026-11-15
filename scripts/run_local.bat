@echo off
rem Windows launcher for run_local.ps1. Works even when PowerShell scripts are
rem blocked (default policy, or files extracted from a downloaded zip).
rem   scripts\run_local.bat           API  -> http://127.0.0.1:8000/docs
rem   scripts\run_local.bat -Mock     Mock -> http://127.0.0.1:8001/docs
rem   scripts\run_local.bat -Reset    start with an empty database
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_local.ps1" %*
if errorlevel 1 pause
