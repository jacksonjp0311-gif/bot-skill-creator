[CmdletBinding()]
param([string]$Python = $env:BSC_PYTHON)
$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$Icon = Join-Path $Root 'docs\assets\bot-skill-creator.ico'
$Launcher = Join-Path $Root 'launch.vbs'

function Stop-Install([string]$Message) {
    Write-Host $Message
    try {
        Add-Type -AssemblyName System.Windows.Forms
        [void][System.Windows.Forms.MessageBox]::Show($Message, 'Bot Skill Creator', [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error)
    } catch {}
    exit 1
}

if (-not (Test-Path -LiteralPath $Icon)) { Stop-Install 'The Bot Skill Creator icon is missing from this folder.' }
if (-not (Test-Path -LiteralPath $Launcher)) { Stop-Install 'The Bot Skill Creator launcher is missing from this folder.' }

$Probe = $null
$ProbePrefix = @()
if ($Python) {
    $Probe = $Python
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $Probe = 'py'
    $ProbePrefix = @('-3')
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $Probe = 'python'
}
if (-not $Probe) { Stop-Install 'Python 3.11 or newer is required. Install it, then run this installer again.' }
& $Probe @ProbePrefix -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ is required"'
if ($LASTEXITCODE -ne 0) { Stop-Install 'Python 3.11 or newer is required. Install it, then run this installer again.' }
$PythonExe = (& $Probe @ProbePrefix -c 'import sys; print(sys.executable)').Trim()
if ($LASTEXITCODE -ne 0 -or -not $PythonExe) { Stop-Install 'Python 3.11 or newer is required. Install it, then run this installer again.' }
Set-Content -LiteralPath (Join-Path $Root '.bsc-python') -Value $PythonExe -Encoding ascii

$Desktop = [Environment]::GetFolderPath('Desktop')
if (-not $Desktop) { Stop-Install 'Windows did not report a Desktop folder.' }
$ShortcutPath = Join-Path $Desktop 'Bot Skill Creator.lnk'
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = Join-Path $env:SystemRoot 'System32\wscript.exe'
$Shortcut.Arguments = "//nologo `"$Launcher`""
$Shortcut.WorkingDirectory = $Root
$Shortcut.IconLocation = "$Icon,0"
$Shortcut.Description = 'Open Bot Skill Creator'
$Shortcut.WindowStyle = 7
$Shortcut.Save()
Write-Host "Bot Skill Creator is on the desktop. Click the icon to open it."
Write-Host $ShortcutPath
