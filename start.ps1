[CmdletBinding()]
param([int]$Port = 8717, [string]$Workspace = (Join-Path $HOME '.bot-skill-creator'), [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
Push-Location $Root
try {
    $Python = $null
    $Prefix = @()
    if (Get-Command py -ErrorAction SilentlyContinue) { $Python = 'py'; $Prefix = @('-3') }
    if (-not $Python) {
        if (Get-Command python -ErrorAction SilentlyContinue) { $Python = 'python' }
    }
    if (-not $Python) { throw 'Python 3.11+ is required. Install it, reopen PowerShell, and run this script.' }
    & $Python @Prefix -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ is required"'
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ is required.' }
    $Launch = @('-m', 'bsc', 'serve', '--port', "$Port", '--workspace', $Workspace)
    if (-not $NoBrowser) { $Launch += '--open' }
    & $Python @Prefix @Launch
    if ($LASTEXITCODE -ne 0) { throw "Bot Skill Creator exited with code $LASTEXITCODE" }
}
finally { Pop-Location }
