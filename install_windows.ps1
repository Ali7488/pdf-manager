$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
Write-Host '=== SlideStitch - Windows setup ===' -ForegroundColor Magenta

$python = $null
$prefix = @()
try { & py -3 -c 'import sys; print(sys.executable)' *> $null; if ($LASTEXITCODE -eq 0) { $python = 'py'; $prefix = @('-3') } } catch {}
if (-not $python) {
    try { & python -c 'import sys; print(sys.executable)' *> $null; if ($LASTEXITCODE -eq 0) { $python = 'python' } } catch {}
}
if (-not $python) {
    Write-Host 'Python is missing; trying Windows Package Manager.'
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { throw 'Install Python 3.13 from python.org, then rerun INSTALL.bat.' }
    & winget install --id Python.Python.3.13 -e --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) { throw 'Could not install Python. Install it from python.org.' }
    throw 'Python was installed. Close this window and run INSTALL.bat again so Windows can update its command paths.'
}
Write-Host 'Creating isolated Python environment...'
& $python @prefix -m venv '.venv'
if ($LASTEXITCODE -ne 0) { throw 'Could not create Python environment.' }
& '.\.venv\Scripts\python.exe' -m pip install --disable-pip-version-check --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'Could not update pip.' }
& '.\.venv\Scripts\python.exe' -m pip install --disable-pip-version-check -r requirements.txt
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
