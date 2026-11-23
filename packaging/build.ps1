<#
.SYNOPSIS
    Builds the PDF Manager Windows installer from a clean checkout.

.DESCRIPTION
    Steps, in order. The script stops at the first failure with a clear message.
      1. Check the tools: uv, Node.js/npm and Inno Setup 6 (iscc).
      2. Build the React frontend (npm ci, npm run build) into frontend\dist.
      3. Install the Python dependencies from uv.lock (uv sync --frozen --no-dev).
      4. Bundle the app with PyInstaller (packaging\pdf-manager.spec)
         into dist\PDF Manager.
      5. Compile the install wizard (packaging\installer.iss) into
         dist\installer\PDF-Manager-Setup-<version>.exe.

    The version comes from the [project] version in pyproject.toml.
    Run from any folder:  powershell -ExecutionPolicy Bypass -File packaging\build.ps1

.NOTES
    Keep this file ASCII-only so Windows PowerShell 5.1 reads it correctly.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# PyInstaller is a build-only tool, so it isn't in pyproject.toml; uv adds it on the fly.
$PyInstallerSpec = 'pyinstaller>=6.10,<7'
$RepoRoot = Split-Path -Parent $PSScriptRoot

function Write-Step {
    <# Prints a visible heading for the next build step. #>
    param([Parameter(Mandatory)] [string] $Message)
    Write-Host ''
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-Native {
    <#
    .SYNOPSIS
        Runs a native command and stops the build if it fails.
    .PARAMETER What
        Plain description used in the error message.
    .PARAMETER Command
        Script block that runs exactly one native command.
    #>
    param(
        [Parameter(Mandatory)] [string] $What,
        [Parameter(Mandatory)] [scriptblock] $Command
    )
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$What failed (exit code $LASTEXITCODE). See the output above."
    }
}

function Assert-Command {
    <#
    .SYNOPSIS
        Stops the build when a required program isn't on PATH.
    .PARAMETER Name
        Command to look for, for example 'uv'.
    .PARAMETER Hint
        How to install it.
    #>
    param(
        [Parameter(Mandatory)] [string] $Name,
        [Parameter(Mandatory)] [string] $Hint
    )
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "'$Name' was not found. $Hint"
    }
}

function Find-Iscc {
    <#
    .SYNOPSIS
        Finds the Inno Setup 6 command-line compiler (ISCC.exe).
    .OUTPUTS
        Full path to ISCC.exe, or $null if Inno Setup isn't installed.
    #>
    $onPath = Get-Command 'iscc.exe' -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }

    $folders = New-Object System.Collections.Generic.List[string]
    # Folders recorded by the Inno Setup installer (machine-wide or per-user).
    $uninstallKeys = @(
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1',
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1',
        'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1'
    )
    foreach ($key in $uninstallKeys) {
        $item = Get-ItemProperty -Path $key -Name 'InstallLocation' -ErrorAction SilentlyContinue
        if ($item -and $item.InstallLocation) { $folders.Add($item.InstallLocation) }
    }
    # Default install folders (choco and winget use these too).
    foreach ($root in @(${env:ProgramFiles(x86)}, $env:ProgramFiles, (Join-Path $env:LOCALAPPDATA 'Programs'))) {
        if ($root) { $folders.Add((Join-Path $root 'Inno Setup 6')) }
    }
    foreach ($folder in $folders) {
        $candidate = Join-Path $folder 'ISCC.exe'
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    return $null
}

function Get-ProjectVersion {
    <#
    .SYNOPSIS
        Reads the [project] version from pyproject.toml.
    .OUTPUTS
        The version string, for example '1.1.1'.
    #>
    $text = Get-Content -Raw -LiteralPath (Join-Path $RepoRoot 'pyproject.toml')
    # The first 'version = "..."' line after the [project] header.
    $match = [regex]::Match($text, '(?ms)^\[project\]\s*$(?:(?!^\[).)*?^version\s*=\s*"([^"]+)"')
    if (-not $match.Success) { throw 'Could not read the version from pyproject.toml ([project] version).' }
    return $match.Groups[1].Value
}

function Remove-IfPresent {
    <# Deletes a file or folder left over from an earlier build. #>
    param([Parameter(Mandatory)] [string] $Path)
    if (Test-Path -LiteralPath $Path) { Remove-Item -LiteralPath $Path -Recurse -Force }
}

Push-Location $RepoRoot
try {
    Write-Step 'Checking the build tools'
    Assert-Command 'uv' 'Install uv from https://docs.astral.sh/uv/ (for example: winget install --id astral-sh.uv -e).'
    # npm.cmd rather than npm: the npm.ps1 shim is blocked when scripts are disabled.
    Assert-Command 'node' 'Install Node.js 24 LTS from https://nodejs.org/.'
    Assert-Command 'npm.cmd' 'npm comes with Node.js. Reinstall Node.js 24 LTS from https://nodejs.org/.'
    $iscc = Find-Iscc
    if (-not $iscc) {
        throw 'Inno Setup 6 (ISCC.exe) was not found. Install it from https://jrsoftware.org/isdl.php (for example: winget install --id JRSoftware.InnoSetup -e).'
    }
    Write-Host "uv:   $((Get-Command uv).Source)"
    Write-Host "node: $(& node --version)"
    Write-Host "iscc: $iscc"

    $version = Get-ProjectVersion
    Write-Host "Version: $version"

    # Inputs that other layers provide. Say clearly which one is missing.
    if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot 'main.py'))) {
        throw 'main.py (the app entry point) is missing from the repository root. Merge the API layer first.'
    }
    $frontend = Join-Path $RepoRoot 'frontend'
    foreach ($file in @('package.json', 'package-lock.json')) {
        if (-not (Test-Path -LiteralPath (Join-Path $frontend $file))) {
            throw "frontend\$file is missing. Merge the frontend first (npm ci needs both package.json and package-lock.json)."
        }
    }

    Write-Step 'Building the frontend (npm ci, npm run build)'
    Push-Location $frontend
    try {
        Invoke-Native 'npm ci' { & npm.cmd ci }
        Invoke-Native 'npm run build' { & npm.cmd run build }
    }
    finally {
        Pop-Location
    }
    if (-not (Test-Path -LiteralPath (Join-Path $frontend 'dist\index.html'))) {
        throw 'The frontend build finished but frontend\dist\index.html is missing. Check the Vite build output (outDir must be dist).'
    }

    Write-Step 'Installing Python dependencies (uv sync --frozen --no-dev)'
    Invoke-Native 'uv sync' { & uv sync --frozen --no-dev }
    & uv run --frozen --no-sync python -c 'import webview, pymupdf'
    if ($LASTEXITCODE -ne 0) {
        throw 'pywebview or PyMuPDF is not installed in .venv. Both must be dependencies in pyproject.toml/uv.lock (pywebview is added with the API layer).'
    }

    Write-Step 'Bundling the app with PyInstaller'
    $appDir = Join-Path $RepoRoot 'dist\PDF Manager'
    Remove-IfPresent $appDir
    Remove-IfPresent (Join-Path $RepoRoot 'build\pyinstaller')
    Invoke-Native 'PyInstaller' {
        & uv run --frozen --no-dev --with $PyInstallerSpec pyinstaller --noconfirm --clean `
            --distpath dist --workpath 'build\pyinstaller' 'packaging\pdf-manager.spec'
    }
    $appExe = Join-Path $appDir 'PDF Manager.exe'
    if (-not (Test-Path -LiteralPath $appExe)) { throw "PyInstaller finished but $appExe is missing." }

    Write-Step 'Compiling the installer (Inno Setup)'
    $installerDir = Join-Path $RepoRoot 'dist\installer'
    Remove-IfPresent $installerDir
    Invoke-Native 'Inno Setup' { & $iscc "/DAppVersion=$version" (Join-Path $RepoRoot 'packaging\installer.iss') }
    $installer = Join-Path $installerDir "PDF-Manager-Setup-$version.exe"
    if (-not (Test-Path -LiteralPath $installer)) { throw "Inno Setup finished but $installer is missing." }

    $sizeMb = [math]::Round((Get-Item -LiteralPath $installer).Length / 1MB, 1)
    Write-Host ''
    Write-Host "Done: $installer ($sizeMb MB)" -ForegroundColor Green
}
catch {
    Write-Host ''
    Write-Host "BUILD FAILED: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    Pop-Location
}
