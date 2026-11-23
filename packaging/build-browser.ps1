<#
.SYNOPSIS
    Builds the portable browser-mode ZIP of PDF Manager for Windows.

.DESCRIPTION
    PDF Manager in the user's own browser (docs/BROWSER_MODE.md), as a folder in a
    ZIP: no installer, no window toolkit. Steps, in order; the first failure stops it.
      1. Check the tools: uv and Node.js/npm.
      2. Build the React frontend (npm ci, npm run build) into frontend\dist.
      3. Bundle with PyInstaller (packaging\pdf-manager.spec, PDF_MANAGER_BUILD=browser)
         from its own environment (build\venv-browser) without the desktop group, so
         pywebview, pythonnet and the WebView2 SDK can't be in it. The developer's
         .venv is left alone.
      4. Check it against the licence notices (scripts\check_licenses.py --build browser).
      5. Copy the project's licences, THIRD_PARTY_NOTICES-browser.md and exactly the
         licence texts of what it ships next to it (scripts\stage_licenses.py), and
         check them byte for byte.
      6. Add READ ME FIRST.txt and zip it:
         dist\PDF-Manager-<version>-browser-windows-x64.zip (and print its SHA-256).

    Run from any folder:  powershell -ExecutionPolicy Bypass -File packaging\build-browser.ps1

.NOTES
    Keep this file ASCII-only so Windows PowerShell 5.1 reads it correctly.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# The same pinned PyInstaller as the installer build (packaging\build.ps1).
$PyInstallerSpec = 'pyinstaller==6.22.3'
$RepoRoot = Split-Path -Parent $PSScriptRoot

function Write-Step {
    param([Parameter(Mandatory)] [string] $Message)
    Write-Host ''
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-Native {
    <# Runs one native command and stops the build if it fails. #>
    param(
        [Parameter(Mandatory)] [string] $What,
        [Parameter(Mandatory)] [scriptblock] $Command
    )
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$What failed (exit code $LASTEXITCODE). See the output above."
    }
}

function Get-ProjectVersion {
    $text = Get-Content -Raw -LiteralPath (Join-Path $RepoRoot 'pyproject.toml')
    $match = [regex]::Match($text, '(?ms)^\[project\]\s*$(?:(?!^\[).)*?^version\s*=\s*"([^"]+)"')
    if (-not $match.Success) { throw 'Could not read the version from pyproject.toml ([project] version).' }
    return $match.Groups[1].Value
}

function Remove-IfPresent {
    param([Parameter(Mandatory)] [string] $Path)
    if (Test-Path -LiteralPath $Path) { Remove-Item -LiteralPath $Path -Recurse -Force }
}

$ReadMe = @'
PDF Manager in your web browser
===============================

1. Before the first start, install the free Microsoft Visual C++ Redistributable (x64),
   version 14.44 or newer, if this PC doesn't have it yet:
       https://aka.ms/vc14/vc_redist.x64.exe
   Installing it needs administrator permission. Without it, PDF Manager says
   "Failed to load Python DLL" when it starts.

2. Keep this whole folder together (for example in Documents), then double-click
   "PDF Manager.exe".

3. PDF Manager opens in your default web browser:
   - Microsoft Edge, Google Chrome, Brave or Chromium: in its own window, with no tabs
     or address bar (app mode).
   - Any other browser, such as Firefox: as a normal tab, at a local address
     (http://127.0.0.1:...). Everything still stays on this PC.
   It needs no internet connection. Your files never leave this PC.

4. PDF Manager keeps running after you close the window, so it opens again quickly.
   To stop it, use Settings > Quit PDF Manager. It also stops by itself after an hour
   without use.

Licences: LICENSING.md, THIRD_PARTY_NOTICES.md and the licenses folder. The app as a
whole is under the GNU AGPL-3.0 (it includes PyMuPDF); the complete source code is at
https://github.com/Ali7488/pdf-manager
'@

Push-Location $RepoRoot
try {
    Write-Step 'Checking the build tools'
    foreach ($tool in @('uv', 'node', 'npm.cmd')) {
        if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "'$tool' was not found." }
    }
    $version = Get-ProjectVersion
    Write-Host "Version: $version"

    Write-Step 'Building the frontend (npm ci, npm run build)'
    Push-Location (Join-Path $RepoRoot 'frontend')
    try {
        Invoke-Native 'npm ci' { & npm.cmd ci }
        Invoke-Native 'npm run build' { & npm.cmd run build }
    }
    finally {
        Pop-Location
    }

    Write-Step 'Bundling browser mode with PyInstaller (no desktop group)'
    $appDir = Join-Path $RepoRoot 'dist\PDF Manager (browser)'
    Remove-IfPresent $appDir
    Remove-IfPresent (Join-Path $RepoRoot 'build\pyinstaller-browser')
    $env:PDF_MANAGER_BUILD = 'browser'
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $RepoRoot 'build\venv-browser'
    try {
        Invoke-Native 'PyInstaller' {
            & uv run --frozen --no-dev --no-group desktop --with $PyInstallerSpec pyinstaller `
                --noconfirm --clean --distpath dist --workpath 'build\pyinstaller-browser' `
                'packaging\pdf-manager.spec'
        }
    }
    finally {
        Remove-Item Env:PDF_MANAGER_BUILD, Env:UV_PROJECT_ENVIRONMENT -ErrorAction SilentlyContinue
    }
    if (-not (Test-Path -LiteralPath (Join-Path $appDir 'PDF Manager.exe'))) {
        throw 'PyInstaller finished but PDF Manager.exe is missing.'
    }

    Write-Step 'Checking the bundle against the licence notices'
    Invoke-Native 'Licence check (repository)' { & uv run --frozen --no-sync python scripts\check_licenses.py repo }
    Invoke-Native 'Licence check (browser bundle)' {
        & uv run --frozen --no-sync python scripts\check_licenses.py bundle $appDir --build browser
    }

    Write-Step 'Adding the licences (exactly those of what it ships)'
    Invoke-Native 'Licence staging' {
        & uv run --frozen --no-sync python scripts\stage_licenses.py $appDir --build browser
    }
    Invoke-Native 'Licence check (staged licences)' {
        & uv run --frozen --no-sync python scripts\check_licenses.py bundle $appDir --installed --build browser
    }
    Set-Content -LiteralPath (Join-Path $appDir 'READ ME FIRST.txt') -Value $ReadMe -Encoding ASCII

    Write-Step 'Zipping'
    $zip = Join-Path $RepoRoot "dist\PDF-Manager-$version-browser-windows-x64.zip"
    Remove-IfPresent $zip
    Compress-Archive -Path $appDir -DestinationPath $zip -CompressionLevel Optimal
    $sizeMb = [math]::Round((Get-Item -LiteralPath $zip).Length / 1MB, 1)
    $sha = (Get-FileHash -Algorithm SHA256 -LiteralPath $zip).Hash.ToLower()
    Write-Host ''
    Write-Host "Done: $zip ($sizeMb MB)" -ForegroundColor Green
    Write-Host "SHA-256: $sha"
}
catch {
    Write-Host ''
    Write-Host "BUILD FAILED: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    Pop-Location
}
