@echo off
rem Starts Docker Desktop if needed, Postgres, then the assistant on http://localhost:8080
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run.ps1" %*
