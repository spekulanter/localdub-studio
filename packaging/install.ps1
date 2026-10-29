<#
 LocalDub Studio installer (Windows PowerShell 5.1+).
 Nothing is installed without asking: every system package (uv, FFmpeg, Ollama) and every model
 download is announced with its source and size first. Use -Yes to accept all prompts.
#>
param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'Programs\LocalDub Studio'),
    [string]$ModelsDir = '',
    [switch]$Yes,
    [switch]$NoShortcuts,
    [switch]$WithExperimental,
    [switch]$WithDiarization,
    [switch]$SkipModels,
    [switch]$SkipOllamaModel,
    [switch]$SkipPrerequisites
)
$ErrorActionPreference = 'Stop'
$Source = $PSScriptRoot
$OllamaModel = 'translategemma:4b'

function Say($m) { Write-Host $m }
function Step($m) { Write-Host ''; Write-Host "== $m" -ForegroundColor Cyan }
function Ask($q) {
    if ($Yes) { Say "$q -> yes (-Yes)"; return $true }
    $a = Read-Host "$q [Y/n]"
    return ($a -eq '' -or $a -match '^[yY]')
}
function Refresh-Path {
    $m = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $u = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$m;$u"
}
function Have($cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Run($exe, [string[]]$arguments) {
    & $exe @arguments | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "$exe $($arguments -join ' ') failed with exit code $LASTEXITCODE" }
}

function Ensure-Tool($cmd, $wingetId, $what, $required) {
    if (Have $cmd) { Say "OK   $what found"; return $true }
    Say "MISSING  $what"
    if (-not (Have 'winget')) {
        Say "  winget is not available. Install $what manually, then run this installer again."
        if ($required) { throw "$what is required" }
        return $false
    }
    if (Ask "Install $what with winget (package '$wingetId', from the official winget repository)?") {
        Run 'winget' @('install', '--id', $wingetId, '-e', '--accept-source-agreements', '--accept-package-agreements')
        Refresh-Path
        if (Have $cmd) { return $true }
        Say "  $what was installed but is not on PATH yet. Close this window and run the installer again."
        throw "$what not found after installation"
    }
    if ($required) { throw "$what is required" }
    return $false
}

Write-Host ''
Write-Host 'LocalDub Studio - local English to Slovak video dubbing' -ForegroundColor Green
Say "Install folder: $InstallDir"
if (-not [Environment]::Is64BitOperatingSystem) { throw '64-bit Windows is required.' }

Step 'Checking your computer'
if (Have 'nvidia-smi') {
    $gpu = (& nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader) -join '; '
    Say "NVIDIA GPU: $gpu"
    Say '  (8 GB of video memory is enough; the app loads one model at a time.)'
} else {
    Say 'WARNING: no NVIDIA GPU / driver found. Dubbing will run on the CPU and be much slower.'
}
$free = [math]::Round((Get-PSDrive -Name ($InstallDir.Substring(0,1))).Free / 1GB, 1)
Say "Free space on the install drive: $free GB (about 6 GB needed; 9 GB with speech removal)"
if ($free -lt 6) { if (-not (Ask 'There may not be enough space. Continue anyway?')) { throw 'Not enough disk space' } }

if (-not $SkipPrerequisites) {
    Step 'Prerequisites'
    [void](Ensure-Tool 'uv' 'astral-sh.uv' 'uv (Python package manager)' $true)
    [void](Ensure-Tool 'ffmpeg' 'Gyan.FFmpeg' 'FFmpeg (video processing)' $true)
    $haveOllama = Ensure-Tool 'ollama' 'Ollama.Ollama' 'Ollama (local translation models)' $false
}

Step 'Copying the application'
if ((Resolve-Path $Source).Path -ne (New-Item -ItemType Directory -Force -Path $InstallDir).FullName) {
    & robocopy $Source $InstallDir /E /NFL /NDL /NJH /NJS /NP /XD data models .venv work samples node_modules __pycache__ | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "File copy failed (robocopy exit code $LASTEXITCODE)" }
}
Say 'Done.'

Step 'Installing Python 3.12 and the app libraries (about 2.5 GB download, several minutes)'
Push-Location $InstallDir
try {
    $syncArgs = @('sync', '--frozen', '--no-dev')
    if ($WithExperimental) { $syncArgs += @('--extra', 'experimental') }
    Run 'uv' $syncArgs

    if ($ModelsDir -ne '') { [Environment]::SetEnvironmentVariable('LOCALDUB_MODELS_DIR', $ModelsDir, 'User'); $env:LOCALDUB_MODELS_DIR = $ModelsDir }

    if (-not $SkipModels) {
        Step 'Model files'
        Say 'Speech recognition (faster-whisper large-v3, about 3 GB) and the Slovak voice (Supertonic 3, about 400 MB)'
        Say 'come from Hugging Face. Optional: speaker detection (46 MB, GitHub, checksum-verified).'
        if (Ask 'Download the models now? (otherwise the first dubbing job downloads them)') {
            $fetch = @('run', '--no-sync', 'localdub', 'fetch-models')
            if ($WithDiarization) { $fetch += '--diarization' }
            if ($WithExperimental) { $fetch += '--experimental' }
            Run 'uv' $fetch
        }
    }
} finally { Pop-Location }

if (-not $SkipOllamaModel -and (Have 'ollama')) {
    Step 'Translation model'
    $have = (& ollama list 2>$null) -join "`n"
    if ($have -match [regex]::Escape($OllamaModel)) { Say "$OllamaModel is already installed." }
    elseif (Ask "Download the translation model $OllamaModel with Ollama (about 3.3 GB)?") {
        try { Run 'ollama' @('pull', $OllamaModel) } catch { Say "Could not pull the model (is Ollama running?). Later run: ollama pull $OllamaModel" }
    }
} elseif (-not (Have 'ollama')) {
    Say "NOTE: Ollama is not installed, so translation will not work until you install it and run: ollama pull $OllamaModel"
}

if (-not $NoShortcuts) {
    Step 'Shortcuts'
    $shell = New-Object -ComObject WScript.Shell
    $targets = @((Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\LocalDub Studio.lnk'))
    if (Ask 'Also create a desktop shortcut?') { $targets += (Join-Path ([Environment]::GetFolderPath('Desktop')) 'LocalDub Studio.lnk') }
    foreach ($t in $targets) {
        $lnk = $shell.CreateShortcut($t)
        $lnk.TargetPath = (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe')
        $lnk.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $InstallDir 'launch.ps1')`""
        $lnk.WorkingDirectory = $InstallDir
        $lnk.Description = 'LocalDub Studio'
        $lnk.Save()
        Say "Created $t"
    }
}

@{ version = ((Get-Content (Join-Path $InstallDir 'VERSION') -Raw -ErrorAction SilentlyContinue) -as [string]).Trim(); installed = (Get-Date -Format o); dir = $InstallDir } |
    ConvertTo-Json | Set-Content -Path (Join-Path $InstallDir 'install.json') -Encoding UTF8

Write-Host ''
Write-Host 'Installed.' -ForegroundColor Green
Say 'Start it from the Start menu ("LocalDub Studio"). A console window opens; the app opens in your browser.'
Say 'Close the console window to quit. Your videos and results stay in the "data" folder of the install folder.'
if (-not $Yes -and (Ask 'Start LocalDub Studio now?')) { Start-Process 'powershell.exe' -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $InstallDir 'launch.ps1') }
