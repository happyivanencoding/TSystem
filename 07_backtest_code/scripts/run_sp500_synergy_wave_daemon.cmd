@echo off
setlocal
set LOG=C:\GoogleDrive\TP\07_backtest_code\runs\ad_hoc\sp500_relative_synergy_20260710\resume_full_loop_logs\wave_daemon.log
set SCRIPT=C:\GoogleDrive\TP\07_backtest_code\scripts\launch_sp500_synergy_fullrun_wave.ps1
set OUTDIR=C:\GoogleDrive\TP\07_backtest_code\runs\ad_hoc\sp500_relative_synergy_20260710

:loop
echo [%date% %time%] launch wave >> "%LOG%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" -OutputDir "%OUTDIR%" -MaxActive 4 -WaveSize 4 >> "%LOG%" 2>>&1
if errorlevel 42 goto done
timeout /t 20 /nobreak >nul
goto loop

:done
echo [%date% %time%] all synergy rows complete; daemon exiting >> "%LOG%"
exit /b 0
