$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m PyInstaller --noconfirm --clean --windowed --onedir --name "Full Album Maker" --paths "$Root\src" "$Root\src\full_album_maker\main.py"
$App = "$Root\dist\Full Album Maker"
New-Item -ItemType Directory -Force "$App\tools\ffmpeg" | Out-Null
New-Item -ItemType Directory -Force "$App\data" | Out-Null
New-Item -ItemType Directory -Force "$App\temp" | Out-Null
New-Item -ItemType Directory -Force "$App\output" | Out-Null
Write-Host "Portable folder siap di: $App"
