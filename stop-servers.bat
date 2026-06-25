@echo off
powershell -ExecutionPolicy Bypass -File "%~dp0stop-servers.ps1" %*
