<# Removes LocalDub Studio: shortcuts and the install folder. Asks before deleting your data and models. #>
param([switch]$Yes, [string]$InstallDir = $PSScriptRoot)
$ErrorActionPreference = 'Stop'
function Ask($q) { if ($Yes) { return $true }; $a = Read-Host "$q [y/N]"; return ($a -match '^[yY]') }

# Run from a temporary copy so the folder (including this script) can be deleted.
if ($PSScriptRoot -eq $InstallDir -and -not $env:LOCALDUB_UNINSTALL_COPY) {
    $tmp = Join-Path $env:TEMP 'localdub-uninstall.ps1'
    Copy-Item $PSCommandPath $tmp -Force
    $env:LOCALDUB_UNINSTALL_COPY = '1'
    $a = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $tmp, '-InstallDir', $InstallDir)
    if ($Yes) { $a += '-Yes' }
    & powershell.exe @a
    exit $LASTEXITCODE
}

Write-Host "This removes LocalDub Studio from $InstallDir"
if (-not (Ask 'Continue?')) { exit 0 }
$keepData = -not (Ask 'Also delete your projects and videos (data folder)?')
$keepModels = -not (Ask 'Also delete the downloaded models (models folder, several GB)?')

foreach ($lnk in @((Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\LocalDub Studio.lnk'),
                   (Join-Path ([Environment]::GetFolderPath('Desktop')) 'LocalDub Studio.lnk'))) {
    if (Test-Path $lnk) { Remove-Item $lnk -Force; Write-Host "Removed $lnk" }
}
Get-ChildItem $InstallDir -Force | Where-Object {
    -not (($keepData -and $_.Name -eq 'data') -or ($keepModels -and $_.Name -eq 'models'))
} | ForEach-Object { Remove-Item $_.FullName -Recurse -Force -ErrorAction Continue }
if (-not ($keepData -and $keepModels)) { Remove-Item $InstallDir -Force -ErrorAction SilentlyContinue }
Write-Host 'LocalDub Studio was removed. (uv, FFmpeg and Ollama were left installed; remove them with winget if you wish.)'
