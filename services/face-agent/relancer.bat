@echo off
REM Lance le service de reconnaissance faciale et le RELANCE automatiquement s'il s'arrete.
REM A double-cliquer. Laisse cette fenetre ouverte pendant toute la demo.
cd /d "%~dp0"
title Reconnaissance faciale RESILIENCE-ALPHA

echo Arret d'un eventuel ancien service sur le port 8070...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8070 " ^| findstr LISTENING') do taskkill /F /PID %%p >nul 2>&1
timeout /t 1 /nobreak >nul

:boucle
echo.
echo === Demarrage du service (%date% %time%) ===
echo (si l'image se fige, ferme puis rouvre ce .bat)
".venv\Scripts\python" -m uvicorn face_service:app --host 127.0.0.1 --port 8070 --no-access-log
echo.
echo *** Le service s'est arrete. Relance automatique dans 2 secondes... ***
timeout /t 2 /nobreak >nul
goto boucle
