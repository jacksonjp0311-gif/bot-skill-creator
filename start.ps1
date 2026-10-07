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

function Format-Arg([string]$Value) {
    if ($Value -match '[\s"]') { return '"' + ($Value -replace '"', '\"') + '"' }
    return $Value
}

function Stop-Start([string]$Message) {
    Write-Host $Message
    cmd /c pause
    exit 1
}

Push-Location $Root
try {
    $Probe = $null
    $ProbePrefix = @()
    if (Get-Command py -ErrorAction SilentlyContinue) { $Probe = 'py'; $ProbePrefix = @('-3') }
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
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $PythonExe
    $psi.Arguments = ((@(
        '-m', 'bsc', 'serve', '--port', "$Port", '--workspace', $Workspace, '--open'
    ) | ForEach-Object { Format-Arg $_ }) -join ' ')
    $psi.WorkingDirectory = $Root
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    if (-not $proc.Start()) { Stop-Start 'Bot Skill Creator could not start.' }
    $stdoutTask = $proc.StandardOutput.ReadToEndAsync()
    $stderrTask = $proc.StandardError.ReadToEndAsync()
    $deadline = [DateTime]::UtcNow.AddSeconds(12)
    $opened = $false
    while ([DateTime]::UtcNow -lt $deadline) {
        if (Test-Studio $Port) { $opened = $true; break }
        if ($proc.HasExited) { break }
        Start-Sleep -Milliseconds 200
    }
    if ($opened) { return }
    if (-not $proc.HasExited) { [void]$proc.WaitForExit(2000) }
    [void]$stdoutTask.Wait(2000)
    [void]$stderrTask.Wait(2000)
    $detail = ("$($stderrTask.Result)`n$($stdoutTask.Result)").Trim()
    if ($proc.HasExited -and $proc.ExitCode -eq 0) { return }
    if (-not $detail) { $detail = "Bot Skill Creator did not open on http://127.0.0.1:$Port/." }
    Stop-Start $detail
}
finally { Pop-Location }
