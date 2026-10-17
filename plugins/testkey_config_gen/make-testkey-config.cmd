@echo off
REM 插件包装脚本：默认暂停（方便在 TUI 里预览 dry-run 结果）且默认不导出 zip。
REM 默认值放在 %* 之前，用户后面的 --export / --no_interactive 可以覆盖它们。
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0make-testkey-config.ps1" --interactive --no_export %*
exit /b %ERRORLEVEL%
