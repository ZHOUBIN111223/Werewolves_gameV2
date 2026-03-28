param()

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Write-Step {
  param([string]$Message)
  Write-Host "[stack] $Message"
}

$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $PSCommandPath }
$root = (Resolve-Path (Join-Path $scriptDir '..')).Path
$statePath = Join-Path $root '.runtime\stack-state.json'

if (!(Test-Path $statePath)) {
  Write-Step "No state file found at $statePath"
  exit 0
}

$state = Get-Content $statePath -Raw | ConvertFrom-Json
$targets = @()

if ($state.live_game.managed -and $state.live_game.pid) {
  $targets += [pscustomobject]@{ pid = $state.live_game.pid; name = 'live_game' }
}

if ($state.frontend.managed -and $state.frontend.pid) {
  $targets += [pscustomobject]@{ pid = $state.frontend.pid; name = 'frontend' }
}

if ($state.api.managed -and $state.api.pid) {
  $targets += [pscustomobject]@{ pid = $state.api.pid; name = 'api' }
}

foreach ($target in $targets) {
  try {
    $process = Get-Process -Id $target.pid -ErrorAction Stop
    Write-Step "Stopping $($target.name) PID $($target.pid) ($($process.ProcessName))"
    Stop-Process -Id $target.pid -Force
  } catch {
    Write-Step "$($target.name) PID $($target.pid) is already stopped"
  }
}

Remove-Item -LiteralPath $statePath -Force
Write-Step 'Workspace services stopped'
