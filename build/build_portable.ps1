$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt

$Url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-n9.0-latest-win64-gpl-9.0.zip"
Invoke-WebRequest -Uri $Url -OutFile ffmpeg.zip
if (Test-Path ffmpeg_unpack) { Remove-Item ffmpeg_unpack -Recurse -Force }
Expand-Archive ffmpeg.zip -DestinationPath ffmpeg_unpack

$Ffmpeg = Get-ChildItem ffmpeg_unpack -Recurse -Filter ffmpeg.exe | Select-Object -First 1
$Ffprobe = Get-ChildItem ffmpeg_unpack -Recurse -Filter ffprobe.exe | Select-Object -First 1
if (-not $Ffmpeg -or -not $Ffprobe) { throw "ffmpeg.exe atau ffprobe.exe tidak ditemukan." }

New-Item -ItemType Directory -Force "$Root\tools\ffmpeg" | Out-Null
Copy-Item $Ffmpeg.FullName "$Root\tools\ffmpeg\ffmpeg.exe" -Force
Copy-Item $Ffprobe.FullName "$Root\tools\ffmpeg\ffprobe.exe" -Force

$Encoders = & "$Root\tools\ffmpeg\ffmpeg.exe" -hide_banner -encoders 2>&1 | Out-String
if ($Encoders -notmatch "libx264") { throw "FFmpeg build tidak memiliki libx264." }
if ($Encoders -notmatch "libx265") { throw "FFmpeg build tidak memiliki libx265." }

python -m pytest -q

$env:QT_QPA_PLATFORM = "offscreen"
python "$Root\build\generate_icon.py"
python -m PyInstaller --noconfirm --clean --windowed --onedir --name "Full Album Maker" --icon "$Root\assets\logo.ico" --paths "$Root\src" "$Root\src\full_album_maker\main.py"

$App = "$Root\dist\Full Album Maker"
New-Item -ItemType Directory -Force "$App\tools\ffmpeg" | Out-Null
Copy-Item "$Root\tools\ffmpeg\ffmpeg.exe" "$App\tools\ffmpeg\ffmpeg.exe" -Force
Copy-Item "$Root\tools\ffmpeg\ffprobe.exe" "$App\tools\ffmpeg\ffprobe.exe" -Force
Copy-Item "$Root\LICENSE" "$App\LICENSE.txt" -Force
Copy-Item "$Root\THIRD_PARTY_NOTICES.md" "$App\THIRD_PARTY_NOTICES.md" -Force
New-Item -ItemType Directory -Force "$App\assets" | Out-Null
Copy-Item "$Root\assets\logo.svg" "$App\assets\logo.svg" -Force

$FfLicense = Get-ChildItem ffmpeg_unpack -Recurse -File | Where-Object { $_.Name -eq "LICENSE.txt" } | Select-Object -First 1
$FfReadme = Get-ChildItem ffmpeg_unpack -Recurse -File | Where-Object { $_.Name -eq "README.txt" } | Select-Object -First 1
if ($FfLicense) { Copy-Item $FfLicense.FullName "$App\FFMPEG-LICENSE.txt" -Force }
if ($FfReadme) { Copy-Item $FfReadme.FullName "$App\FFMPEG-README.txt" -Force }

New-Item -ItemType Directory -Force "$App\data" | Out-Null
New-Item -ItemType Directory -Force "$App\temp" | Out-Null
New-Item -ItemType Directory -Force "$App\output" | Out-Null

$Zip = "$Root\Full-Album-Maker-Windows-Portable.zip"
if (Test-Path $Zip) { Remove-Item $Zip -Force }
Compress-Archive -Path "$App" -DestinationPath $Zip

Write-Host "Portable ZIP siap di: $Zip"
