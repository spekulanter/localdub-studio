<# Starts LocalDub Studio and opens it in the browser. Close this window to quit. #>
param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$Host.UI.RawUI.WindowTitle = 'LocalDub Studio (close this window to quit)'
$url = 'http://127.0.0.1:8765'

function Healthy { try { (Invoke-WebRequest "$url/api/health" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 } catch { $false } }

if (Healthy) {
    Write-Host 'LocalDub Studio is already running.'
    if (-not $NoBrowser) { Start-Process $url }
    exit 0
}
foreach ($tool in 'uv', 'ffmpeg') {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        Write-Host "$tool was not found on PATH. Run the installer again, or log out and in." -ForegroundColor Red
        Read-Host 'Press Enter to close'; exit 1
    }
}
if (-not $NoBrowser) {
    Start-Job -ScriptBlock {
        param($u)
        for ($i = 0; $i -lt 90; $i++) {
            try { if ((Invoke-WebRequest "$u/api/health" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200) { Start-Process $u; break } } catch { Start-Sleep -Seconds 1 }
        }
    } -ArgumentList $url | Out-Null
}
Write-Host "LocalDub Studio is starting at $url (this window shows its log)"
& uv run --no-sync localdub serve
if ($LASTEXITCODE -ne 0) { Read-Host 'The server stopped with an error. Press Enter to close' }
