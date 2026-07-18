# Launch a clean, fixed-geometry Chrome with the DevTools protocol open, so the
# take is reproducible and the gdigrab crop region never moves.
#
#   .\launch-chrome.ps1
#
# Uses a throwaway profile so no bookmarks bar / extensions / restore bubble
# pollute the frame.

$ErrorActionPreference = "Stop"

$Port = 9222
$Profile = Join-Path $env:TEMP "wfc-demo-chrome-profile"
# 3001, NOT 3000 -- port 3000 is a different app on this machine (ScopeNotes).
# Pointing this at 3000 records 26 minutes of the wrong application.
$Url = "http://localhost:3001/"

# Window geometry, in DIPs (this display is 1920x1200 physical at 125% scaling,
# so the logical desktop is only 1536x960 and the work area 1536x912).
#
# 1600x1000 did NOT fit: Chrome clamped it, and the resulting 1539-CSS-px
# viewport came to 1539 * 1.25 = 1924 physical px -- 4px WIDER than the screen,
# so the right edge of the app fell outside the recording. Keep the viewport
# inside 1920x1200 physical with room to spare.
$WinX = 0
$WinY = 0
$WinW = 1520
$WinH = 900

$chrome = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $chrome) { throw "Chrome not found." }

if (Test-Path $Profile) { Remove-Item -Recurse -Force $Profile }
New-Item -ItemType Directory -Force -Path $Profile | Out-Null

$chromeArgs = @(
    "--remote-debugging-port=$Port"
    "--user-data-dir=$Profile"
    "--window-position=$WinX,$WinY"
    "--window-size=$WinW,$WinH"
    "--no-first-run"
    "--no-default-browser-check"
    "--hide-crash-restore-bubble"
    "--disable-extensions"
    "--disable-infobars"
    "--test-type"                       # suppresses the "unsupported flag" infobar
    # NOTE: --force-device-scale-factor=1 used to be here, claiming to make
    # CSS px == device px. It does not work (devicePixelRatio stays 1.25 on this
    # display), so it was a lie that misled the crop math. Removed. We do not
    # need it: calibrate.py *measures* the viewport->video transform from the
    # colour flash, which is correct at any DPR.
    $Url
)

Write-Host "Launching Chrome -> $Url  (CDP on :$Port)"
Start-Process -FilePath $chrome -ArgumentList $chromeArgs

Start-Sleep -Seconds 3
Write-Host "Chrome up. Attach the devtools MCP to http://localhost:$Port"
Write-Host ""
Write-Host "!! Chrome IGNORES --window-size/--window-position here and opens maximized," -ForegroundColor Yellow
Write-Host "   which makes the viewport 1924 physical px wide -- 4px wider than the 1920px" -ForegroundColor Yellow
Write-Host "   screen, so the app's right edge falls outside the recording." -ForegroundColor Yellow
Write-Host "   Over the devtools MCP, resize the page to 1500x790 before recording:" -ForegroundColor Yellow
Write-Host "     resize_page(width=1500, height=790)   -> 1875x988 physical, fits with margin" -ForegroundColor Yellow
Write-Host "   Then verify: innerWidth*devicePixelRatio <= 1920." -ForegroundColor Yellow
