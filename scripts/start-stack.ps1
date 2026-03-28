param(
  [switch]$RunLiveGame,
  [switch]$NoLiveGame,
  [switch]$NoBrowser,
  [string]$FrontendHost = '127.0.0.1',
  [int]$ApiPort = 8000,
  [string]$ApiHost = '127.0.0.1',
  [string]$ApiProvider = 'bailian',
  [string]$BailianApiKey = $env:BAILIAN_API_KEY,
  [string]$BailianEndpoint = 'https://coding.dashscope.aliyuncs.com/v1',
  [string]$BailianModel = 'qwen3-max-2026-01-23',
  [string]$GameConfig = '6_players',
  [int]$Games = 1,
  [switch]$StopExistingWorkspaceServices
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Write-Step {
  param([string]$Message)
  Write-Host "[stack] $Message"
}

function Get-WorkspaceRoot {
  $scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $PSCommandPath }
  return (Resolve-Path (Join-Path $scriptDir '..')).Path
}

function Ensure-Dir {
  param([string]$Path)
  if (!(Test-Path $Path)) {
    New-Item -ItemType Directory -Path $Path | Out-Null
  }
}

function Get-ListeningProcessId {
  param([int]$Port)
  $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($conn) {
    return $conn.OwningProcess
  }
  return $null
}

function Get-ProcessCommandLine {
  param([int]$ProcessId)
  $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
  if ($process) {
    return [string]$process.CommandLine
  }
  return ''
}

function Stop-WorkspaceServiceIfMatch {
  param(
    [int]$Port,
    [string[]]$Matchers
  )

  $pid = Get-ListeningProcessId -Port $Port
  if (-not $pid) {
    return
  }

  $commandLine = Get-ProcessCommandLine -ProcessId $pid
  $matched = $false

  foreach ($matcher in $Matchers) {
    if ($commandLine -like "*$matcher*") {
      $matched = $true
      break
    }
  }

  if ($matched) {
    Write-Step "Stopping existing workspace service on port $Port (PID $pid)"
    Stop-Process -Id $pid -Force
    Start-Sleep -Seconds 2
    return
  }

  throw "Port $Port is already occupied by another process: $commandLine"
}

function Get-AvailableFrontendPort {
  param([int[]]$Candidates)
  foreach ($candidate in $Candidates) {
    if (-not (Get-ListeningProcessId -Port $candidate)) {
      return $candidate
    }
  }
  throw "No free frontend port found in candidates: $($Candidates -join ', ')"
}

function Test-Url {
  param(
    [string]$Url,
    [int]$Attempts = 20,
    [int]$DelaySeconds = 1
  )

  for ($i = 0; $i -lt $Attempts; $i++) {
    try {
      $response = Invoke-WebRequest -Uri $Url -TimeoutSec 5 -UseBasicParsing
      return $response.StatusCode
    } catch {
      Start-Sleep -Seconds $DelaySeconds
    }
  }

  return $null
}

function Get-MatchIds {
  param([string]$ApiBaseUrl)

  try {
    $response = Invoke-RestMethod -Uri "$ApiBaseUrl/api/matches" -TimeoutSec 5 -Method Get
    if ($response -and $response.items) {
      return @($response.items | ForEach-Object { [string]$_.match_id })
    }
  } catch {
    return @()
  }

  return @()
}

function Wait-ForNewMatch {
  param(
    [string]$ApiBaseUrl,
    [string[]]$KnownMatchIds,
    [int]$Attempts = 20,
    [int]$DelaySeconds = 1
  )

  for ($i = 0; $i -lt $Attempts; $i++) {
    $currentMatchIds = Get-MatchIds -ApiBaseUrl $ApiBaseUrl
    $newMatchId = $currentMatchIds | Where-Object { $_ -notin $KnownMatchIds } | Select-Object -First 1
    if ($newMatchId) {
      return [string]$newMatchId
    }

    Start-Sleep -Seconds $DelaySeconds
  }

  return $null
}

$root = Get-WorkspaceRoot
$frontendDir = Join-Path $root 'frontend'
$backendDir = Join-Path $root 'backend'
$runtimeDir = Join-Path $root '.runtime'
$logsDir = Join-Path $runtimeDir 'logs'
$timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'

Ensure-Dir $runtimeDir
Ensure-Dir $logsDir

if (!(Test-Path $frontendDir)) {
  throw "Frontend directory not found: $frontendDir"
}

if (!(Test-Path $backendDir)) {
  throw "Backend directory not found: $backendDir"
}

$frontendPort = Get-AvailableFrontendPort -Candidates @(5173, 5174, 5175, 5176, 5177)

if ($StopExistingWorkspaceServices) {
  Stop-WorkspaceServiceIfMatch -Port $ApiPort -Matchers @('uvicorn src.api.main:app', 'python -m uvicorn src.api.main:app')
  Stop-WorkspaceServiceIfMatch -Port $frontendPort -Matchers @('\vite\bin\vite.js', 'npm run dev')
}

if (Get-ListeningProcessId -Port $ApiPort) {
  $apiCommandLine = Get-ProcessCommandLine -ProcessId (Get-ListeningProcessId -Port $ApiPort)
  if ($apiCommandLine -notlike '*uvicorn src.api.main:app*') {
    throw "API port $ApiPort is occupied by another process: $apiCommandLine"
  }
}

$apiOutLog = Join-Path $logsDir "api_$timestamp.out.log"
$apiErrLog = Join-Path $logsDir "api_$timestamp.err.log"
$frontendOutLog = Join-Path $logsDir "frontend_$timestamp.out.log"
$frontendErrLog = Join-Path $logsDir "frontend_$timestamp.err.log"
$gameOutLog = Join-Path $logsDir "game_$timestamp.out.log"
$gameErrLog = Join-Path $logsDir "game_$timestamp.err.log"

$storePath = Join-Path $backendDir 'store_data\bailian_live'
$logPath = Join-Path $backendDir 'logs\bailian_live'
Ensure-Dir $storePath
Ensure-Dir $logPath

$shouldRunLiveGame = $RunLiveGame -or (-not $NoLiveGame)

if ($shouldRunLiveGame -and [string]::IsNullOrWhiteSpace($BailianApiKey)) {
  if ($RunLiveGame) {
    throw 'BAILIAN_API_KEY is required when -RunLiveGame is specified.'
  }

  Write-Step 'BAILIAN_API_KEY not found. Starting frontend and observer API without launching a live game.'
  $shouldRunLiveGame = $false
}

$apiProcess = $null
$frontendProcess = $null
$gameProcess = $null
$apiManaged = $false
$frontendManaged = $false
$gameManaged = $false
$newMatchId = $null

if (-not (Get-ListeningProcessId -Port $ApiPort)) {
  Write-Step "Starting observer API on http://$ApiHost`:$ApiPort"
  $previousStorePath = $env:STORE_PATH
  $previousLogPath = $env:LOG_PATH
  $env:STORE_PATH = $storePath
  $env:LOG_PATH = $logPath
  $apiProcess = Start-Process -FilePath python -ArgumentList @('-m', 'uvicorn', 'src.api.main:app', '--host', $ApiHost, '--port', $ApiPort) -WorkingDirectory $backendDir -RedirectStandardOutput $apiOutLog -RedirectStandardError $apiErrLog -PassThru
  $env:STORE_PATH = $previousStorePath
  $env:LOG_PATH = $previousLogPath
  $apiManaged = $true
} else {
  Write-Step "Observer API already running on port $ApiPort"
}

$apiStatus = Test-Url -Url "http://$ApiHost`:$ApiPort/health"
if (-not $apiStatus) {
  throw "Observer API failed to become ready. Check logs: $apiErrLog"
}

$apiUrl = "http://$ApiHost`:$ApiPort"
$knownMatchIds = Get-MatchIds -ApiBaseUrl $apiUrl

if ($shouldRunLiveGame) {
  Write-Step "Starting Bailian live game in background"
  $previousBailianApiKey = $env:BAILIAN_API_KEY
  $previousBailianEndpoint = $env:BAILIAN_ENDPOINT
  $previousBailianModel = $env:BAILIAN_DEFAULT_MODEL
  $previousStorePath = $env:STORE_PATH
  $previousLogPath = $env:LOG_PATH
  $previousApiTimeout = $env:API_TIMEOUT
  $env:BAILIAN_API_KEY = $BailianApiKey
  $env:BAILIAN_ENDPOINT = $BailianEndpoint
  $env:BAILIAN_DEFAULT_MODEL = $BailianModel
  $env:STORE_PATH = $storePath
  $env:LOG_PATH = $logPath
  $env:API_TIMEOUT = '120'
  $gameProcess = Start-Process -FilePath python -ArgumentList @('main.py', '--api-provider', $ApiProvider, '--model', $BailianModel, '--games', $Games, '--game-config', $GameConfig) -WorkingDirectory $backendDir -RedirectStandardOutput $gameOutLog -RedirectStandardError $gameErrLog -PassThru
  $env:BAILIAN_API_KEY = $previousBailianApiKey
  $env:BAILIAN_ENDPOINT = $previousBailianEndpoint
  $env:BAILIAN_DEFAULT_MODEL = $previousBailianModel
  $env:STORE_PATH = $previousStorePath
  $env:LOG_PATH = $previousLogPath
  $env:API_TIMEOUT = $previousApiTimeout
  $gameManaged = $true

  $newMatchId = Wait-ForNewMatch -ApiBaseUrl $apiUrl -KnownMatchIds $knownMatchIds -Attempts 20 -DelaySeconds 1
  if ($newMatchId) {
    Write-Step "Detected new live match: $newMatchId"
  } else {
    Write-Step "Live game started, but no new match was detected before frontend launch"
  }
}

Write-Step "Starting frontend on http://$FrontendHost`:$frontendPort"
$frontendProcess = Start-Process -FilePath npm.cmd -ArgumentList @('run', 'dev', '--', '--host', $FrontendHost, '--port', $frontendPort) -WorkingDirectory $frontendDir -RedirectStandardOutput $frontendOutLog -RedirectStandardError $frontendErrLog -PassThru
$frontendManaged = $true

$frontendStatus = Test-Url -Url "http://$FrontendHost`:$frontendPort"
if (-not $frontendStatus) {
  throw "Frontend failed to become ready. Check logs: $frontendErrLog"
}

$apiListenerPid = Get-ListeningProcessId -Port $ApiPort
$frontendListenerPid = Get-ListeningProcessId -Port $frontendPort

$state = [pscustomobject]@{
  started_at = (Get-Date).ToString('s')
  api = [pscustomobject]@{
    host = $ApiHost
    port = $ApiPort
    pid = if ($apiListenerPid) { $apiListenerPid } else { $apiProcess.Id }
    managed = $apiManaged
    out_log = $apiOutLog
    err_log = $apiErrLog
  }
  frontend = [pscustomobject]@{
    host = $FrontendHost
    port = $frontendPort
    pid = if ($frontendListenerPid) { $frontendListenerPid } else { $frontendProcess.Id }
    managed = $frontendManaged
    out_log = $frontendOutLog
    err_log = $frontendErrLog
  }
  live_game = [pscustomobject]@{
    enabled = [bool]$shouldRunLiveGame
    pid = if ($gameProcess) { $gameProcess.Id } else { $null }
    managed = $gameManaged
    out_log = $gameOutLog
    err_log = $gameErrLog
    store_path = $storePath
    model = $BailianModel
    match_id = $newMatchId
  }
}

$statePath = Join-Path $runtimeDir 'stack-state.json'
$state | ConvertTo-Json -Depth 6 | Set-Content -Path $statePath -Encoding utf8

$frontendUrl = "http://$FrontendHost`:$frontendPort"
$apiUrl = "http://$ApiHost`:$ApiPort"

Write-Host ''
Write-Host 'Werewolf stack is ready.'
Write-Host "Frontend: $frontendUrl"
Write-Host "Observer API: $apiUrl"
Write-Host "State file: $statePath"
Write-Host "Frontend log: $frontendOutLog"
Write-Host "API log: $apiOutLog"
if ($shouldRunLiveGame) {
  Write-Host "Live game log: $gameOutLog"
  if ($newMatchId) {
    Write-Host "Live match: $newMatchId"
  }
}

if (-not $NoBrowser) {
  Start-Process $frontendUrl | Out-Null
}
