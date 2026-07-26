$ErrorActionPreference = "Stop"
& "C:\GoogleDrive\TP\07_backtest_code\scripts\launch_sp500_synergy_wave.ps1" `
    -OutputDir "C:\GoogleDrive\TP\07_backtest_code\runs\ad_hoc\sp500_relative_synergy_20260710" `
    -MaxActive 4 `
    -WaveSize 4 `
    -TaskName "TP_SP500_SynergyWave"
