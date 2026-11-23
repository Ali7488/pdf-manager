$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
Write-Host '=== PDF Manager - Windows setup ===' -ForegroundColor Magenta

# uv manages Python itself, so no separate Python install is needed.
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host 'Installing uv (Python package manager)...'
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { throw 'Install uv from https://docs.astral.sh/uv/, then rerun INSTALL.bat.' }
    & winget install --id astral-sh.uv -e --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) { throw 'Could not install uv. Install it from https://docs.astral.sh/uv/.' }
    # Pick up the new PATH entry without reopening the window.
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'uv was installed. Close this window and run INSTALL.bat again.' }
}
Write-Host 'Creating isolated Python environment...'
& uv sync --frozen --no-dev
if ($LASTEXITCODE -ne 0) { throw 'Could not install Python dependencies.' }

$tesseract = @('C:\Program Files\Tesseract-OCR\tesseract.exe', 'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe') | Where-Object { Test-Path $_ }
if (-not $tesseract -and -not (Get-Command tesseract -ErrorAction SilentlyContinue)) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host 'Installing OCR engine (Tesseract)...'
        & winget install --id UB-Mannheim.TesseractOCR -e --accept-source-agreements --accept-package-agreements
        if ($LASTEXITCODE -ne 0) { Write-Warning 'Could not install Tesseract automatically. See README.' }
    } else { Write-Warning 'Install Tesseract from github.com/UB-Mannheim/tesseract/wiki.' }
}
# LibreOffice is only needed when Microsoft PowerPoint cannot handle PPT/PPTX conversion.
$office = @('C:\Program Files\LibreOffice\program\soffice.exe', 'C:\Program Files (x86)\LibreOffice\program\soffice.exe') | Where-Object { Test-Path $_ }
if (-not $office) {
    Write-Host 'Installing LibreOffice for reliable PowerPoint import/export...'
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        & winget install --id TheDocumentFoundation.LibreOffice -e --accept-source-agreements --accept-package-agreements
        if ($LASTEXITCODE -ne 0) { Write-Warning 'LibreOffice installation did not finish. PowerPoint conversion may still work if Office is installed.' }
    } else { Write-Warning 'Install LibreOffice from libreoffice.org if you need PPT/PPTX conversion.' }
}
Write-Host ''
Write-Host 'SETUP COMPLETE. Open OPEN.bat to launch the converter.' -ForegroundColor Green
Write-Host 'You may create a Desktop shortcut to OPEN.bat.'
