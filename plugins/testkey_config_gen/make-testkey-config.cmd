@echo off
REM Plugin launcher. The defaults below come before %*, so a later flag from the
REM caller wins:  --export overrides --no_export, --no_interactive overrides
REM --interactive.
REM   --interactive : pause at the end, so the dry-run preview stays readable
REM                   when the plugin is launched from the TUI.
REM   --no_export   : do not export a zip by default.
REM KEEP THIS FILE ASCII-ONLY. cmd.exe reads batch files with the OEM code page,
REM so non-ASCII bytes (for example Chinese comments) shift the byte stream and
REM break line parsing -- the fragments then run as commands and the launcher
REM exits with 9009. Put translated text in the .ps1 or in README.md instead.
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0make-testkey-config.ps1" --interactive --no_export %*
exit /b %ERRORLEVEL%
