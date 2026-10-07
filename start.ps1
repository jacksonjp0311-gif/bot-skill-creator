[CmdletBinding()]
param([int]$Port = 8717, [string]$Workspace = (Join-Path $HOME '.bot-skill-creator'), [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot

function Test-Studio([int]$ListenPort) {
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$ListenPort/" -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200 -and $response.Content -match 'Bot Skill Creator'
    } catch {
        return $false
    }
}

function Stop-Start([string]$Message) {
    Write-Host $Message
    if ($env:BSC_DESKTOP -eq '1') {
        Add-Type -AssemblyName System.Windows.Forms
        [void][System.Windows.Forms.MessageBox]::Show($Message, 'Bot Skill Creator', [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error)
        exit 1
    }
    cmd /c pause
    exit 1
}

Push-Location $Root
try {
    $Probe = $null
    $ProbePrefix = @()
    if ($env:BSC_PYTHON) { $Probe = $env:BSC_PYTHON }
    elseif (Get-Command py -ErrorAction SilentlyContinue) { $Probe = 'py'; $ProbePrefix = @('-3') }
    elseif (Get-Command python -ErrorAction SilentlyContinue) { $Probe = 'python' }
    if (-not $Probe) { Stop-Start 'Python 3.11+ is required. Install it, reopen PowerShell, and run this script.' }
    $PythonExe = (& $Probe @ProbePrefix -c 'import sys; print(sys.executable)').Trim()
    if ($LASTEXITCODE -ne 0 -or -not $PythonExe) { Stop-Start 'Python 3.11+ is required.' }
    & $PythonExe -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ is required"'
    if ($LASTEXITCODE -ne 0) { Stop-Start 'Python 3.11+ is required.' }
    if ($NoBrowser) {
        & $PythonExe -m bsc serve --stay --port "$Port" --workspace $Workspace
        if ($LASTEXITCODE -ne 0) { throw "Bot Skill Creator exited with code $LASTEXITCODE" }
        return
    }
    if (Test-Studio $Port) {
        Start-Process "http://127.0.0.1:$Port/"
        return
    }
    $proc = Start-Process -FilePath $PythonExe -ArgumentList @(
        '-m', 'bsc', 'serve', '--port', "$Port", '--workspace', $Workspace, '--no-browser'
    ) -WorkingDirectory $Root -WindowStyle Hidden -PassThru
    $deadline = [DateTime]::UtcNow.AddSeconds(12)
    $opened = $false
    while ([DateTime]::UtcNow -lt $deadline) {
        if (Test-Studio $Port) { $opened = $true; break }
        if ($proc.HasExited) { break }
        Start-Sleep -Milliseconds 200
    }
    if ($opened) {
        Start-Process "http://127.0.0.1:$Port/"
        return
    }
    if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
    Stop-Start "Bot Skill Creator did not open on http://127.0.0.1:$Port/."
}
finally { Pop-Location }
