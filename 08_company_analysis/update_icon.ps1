# Ensure we are in the script's directory
Set-Location $PSScriptRoot

$IconPng = "icon.png"
$IconIco = "app.ico"

# 1. Check if icon.png exists
if (-not (Test-Path $IconPng)) {
    Write-Host "请先将您发送的图片保存为项目根目录下的 'icon.png' 文件。" -ForegroundColor Red
    Write-Host "Please save your image as 'icon.png' in this folder: $PWD" -ForegroundColor Yellow
    exit
}

# 2. Convert to .ico using Python
Write-Host "Converting PNG to ICO format..." -ForegroundColor Cyan
if (-not (Test-Path "backend\venv")) {
     # Fallback if venv not set up (unlikely if app ran)
     python backend/convert_icon.py $IconPng
} else {
     .\backend\venv\Scripts\python.exe backend/convert_icon.py $IconPng
}

if (-not (Test-Path $IconIco)) {
    Write-Host "Icon conversion failed." -ForegroundColor Red
    exit
}

# 3. Update Shortcut
$WshShell = New-Object -comObject WScript.Shell
$DesktopPath = $WshShell.SpecialFolders.Item("Desktop")
$ShortcutPath = Join-Path $DesktopPath "Company Analysis.lnk"
$TargetScript = Join-Path $PWD "start_app.ps1"
$IconAbsolutePath = Join-Path $PWD $IconIco

if (Test-Path $ShortcutPath) {
    $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = "powershell.exe"
    $Shortcut.Arguments = "-ExecutionPolicy Bypass -NoExit -File `"$TargetScript`""
    $Shortcut.WorkingDirectory = $PWD
    $Shortcut.IconLocation = $IconAbsolutePath
    $Shortcut.Save()
    Write-Host "Shortcut icon updated successfully!" -ForegroundColor Green
} else {
    Write-Host "Shortcut not found on Desktop. Creating new one..." -ForegroundColor Yellow
    $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = "powershell.exe"
    $Shortcut.Arguments = "-ExecutionPolicy Bypass -NoExit -File `"$TargetScript`""
    $Shortcut.WorkingDirectory = $PWD
    $Shortcut.WindowStyle = 1
    $Shortcut.Description = "Launch Company Analysis App"
    $Shortcut.IconLocation = $IconAbsolutePath
    $Shortcut.Save()
    Write-Host "New shortcut created with custom icon!" -ForegroundColor Green
}


