@echo off
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0make-testkey-config.ps1" %*
exit /b %ERRORLEVEL%
