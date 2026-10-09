@echo off
rem Gives the locally running assistant a temporary public link (start it with run.cmd first)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\share.ps1" %*
