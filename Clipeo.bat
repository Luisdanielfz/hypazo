@echo off
rem Abre la app de clipeo. Doble clic; cierra esta ventana para apagarla.
title Clipeo
cd /d "%~dp0"
python app.py
if errorlevel 1 pause
