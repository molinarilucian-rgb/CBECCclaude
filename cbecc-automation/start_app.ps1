<#
start_app.ps1 — start the CBECC CF1R local web app and open the browser.

Double-click target for daily use. Delegates to run.ps1 (which finds the real
Python, ignoring the Windows Store stub) and launches app.py. The app binds to
127.0.0.1:8765 and opens your browser automatically.

    .\start_app.ps1               # serve on :8765, open browser
    .\start_app.ps1 -Port 9000    # custom port

If PowerShell blocks the script:
    powershell -ExecutionPolicy Bypass -File .\start_app.ps1
#>
param(
    [int]$Port = 8765
)

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$run = Join-Path $here 'run.ps1'

Write-Host "Starting CBECC CF1R automation on http://localhost:$Port ..." -ForegroundColor Cyan
Write-Host "Leave this window open. Press Ctrl+C here to stop the app." -ForegroundColor DarkGray

& powershell -ExecutionPolicy Bypass -File $run app.py --port $Port
