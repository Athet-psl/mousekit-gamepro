# Builds dist\Mousekit\ (mousekit.exe, mousekitd.exe) and, with Inno Setup installed, dist\mousekit-setup-VERSION.exe.
#   packaging\windows\build.ps1 -Version 0.2.7 [-Python path\to\python.exe]
# Needs: pip install PyQt6 pyinstaller
param(
    [string]$Version = "0.2.0",
    [string]$Python = "python"
)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
Set-Location $root

$parts = ($Version.Split(".") + @("0", "0", "0", "0"))[0..3] -join ", "
New-Item -ItemType Directory -Force build | Out-Null
Set-Content -Encoding utf8 mousekit\_build.py "__version__ = `"$Version`""
Set-Content -Encoding utf8 build\version-info.txt @"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($parts), prodvers=($parts)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Athet-psl'),
      StringStruct('FileDescription', 'Mousekit for GamePro'),
      StringStruct('FileVersion', '$Version'),
      StringStruct('ProductName', 'Mousekit for GamePro'),
      StringStruct('ProductVersion', '$Version'),
      StringStruct('LegalCopyright', 'MIT license')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"@
try {
    & $Python -m PyInstaller --noconfirm --clean --distpath dist --workpath build\pyinstaller packaging\windows\mousekit.spec
    if ($LASTEXITCODE) { throw "PyInstaller failed" }
} finally {
    Remove-Item mousekit\_build.py -ErrorAction SilentlyContinue
}
Copy-Item LICENSE, README.md dist\Mousekit\

$iscc = @(
    (Get-Command iscc -ErrorAction SilentlyContinue).Source,
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $iscc) {
    Write-Host "Inno Setup not found: built dist\Mousekit only."
    exit 0
}
& $iscc /Qp "/DVersion=$Version" "/DSource=$root\dist\Mousekit" "/O$root\dist" packaging\windows\mousekit.iss
if ($LASTEXITCODE) { throw "Inno Setup failed" }
