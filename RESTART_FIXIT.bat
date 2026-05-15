@echo off
setlocal EnableExtensions
title FixIt — Restart
REM Same launcher as START_FIXIT: single instance then start (elevated).

cd /d "%~dp0"
call "%~dp0START_FIXIT.bat"
