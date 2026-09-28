$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Assert-NativeSuccess {
    param([Parameter(Mandatory = $true)][string]$Step)
    if ($LASTEXITCODE -ne 0) {
        throw "$Step gagal (exit code $LASTEXITCODE)."
    }
}

$Version = python -c "import sys; sys.path.insert(0, 'src'); import full_album_maker; print(full_album_maker.__version__)"
Assert-NativeSuccess "Baca versi aplikasi"
$Version = $Version.Trim()
if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    throw "Versi release harus semantic version stabil, contoh 1.0.0. Ditemukan: $Version"
}
$ReleaseZipName = "Full-Album-Maker-v$Version-Windows-Portable.zip"

# Keep the local release path aligned with CI. A developer running this script
# should get the same dependency family, FFmpeg digest, font fallback, capability
# report, and extracted-ZIP smoke contract as the GitHub Actions artifact.
python -m pip install pip==26.2.1
Assert-NativeSuccess "Pin pip"
python -m pip install -r build/requirements-windows.lock
Assert-NativeSuccess "Install dependency Python terkunci"

$FfmpegUrl = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-n9.0-latest-win64-gpl-9.0.zip"
$FfmpegSha256 = "b745ed683204c8e154d627bf75f2e530b7b2eec51d14fabdc8771912423ba67e"
if (Test-Path ffmpeg.zip) { Remove-Item ffmpeg.zip -Force }
if (Test-Path ffmpeg_unpack) { Remove-Item ffmpeg_unpack -Recurse -Force }
Invoke-WebRequest -Uri $FfmpegUrl -OutFile ffmpeg.zip
$ActualFfmpegSha = (Get-FileHash ffmpeg.zip -Algorithm SHA256).Hash.ToLowerInvariant()
if ($ActualFfmpegSha -ne $FfmpegSha256) {
    throw "Digest FFmpeg berubah. Expected $FfmpegSha256, got $ActualFfmpegSha. Update pin secara eksplisit."
}
Expand-Archive ffmpeg.zip -DestinationPath ffmpeg_unpack

$Ffmpeg = Get-ChildItem ffmpeg_unpack -Recurse -Filter ffmpeg.exe | Select-Object -First 1
$Ffprobe = Get-ChildItem ffmpeg_unpack -Recurse -Filter ffprobe.exe | Select-Object -First 1
if (-not $Ffmpeg -or -not $Ffprobe) { throw "ffmpeg.exe atau ffprobe.exe tidak ditemukan." }

New-Item -ItemType Directory -Force "$Root\tools\ffmpeg" | Out-Null
Copy-Item $Ffmpeg.FullName "$Root\tools\ffmpeg\ffmpeg.exe" -Force
Copy-Item $Ffprobe.FullName "$Root\tools\ffmpeg\ffprobe.exe" -Force

$FfDir = (Resolve-Path "$Root\tools\ffmpeg").Path
$OldPathForBuild = $env:PATH
$env:PATH = "$FfDir;$env:PATH"

$Encoders = & "$Root\tools\ffmpeg\ffmpeg.exe" -hide_banner -encoders 2>&1 | Out-String
Assert-NativeSuccess "Pemeriksaan encoder FFmpeg"
if ($Encoders -notmatch "libx264") { throw "FFmpeg build tidak memiliki libx264." }
if ($Encoders -notmatch "libx265") { throw "FFmpeg build tidak memiliki libx265." }

$FontCommit = "23e54b51ddffbc7713c583748e3bd86f62b1fa4a"
New-Item -ItemType Directory -Force "$Root\assets\fonts" | Out-Null
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/google/fonts/$FontCommit/ofl/notosans/NotoSans%5Bwdth%2Cwght%5D.ttf" -OutFile "$Root\assets\fonts\NotoSans.ttf"
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/google/fonts/$FontCommit/ofl/notosans/OFL.txt" -OutFile "$Root\assets\fonts\NotoSans-OFL.txt"
if ((Get-Item "$Root\assets\fonts\NotoSans.ttf").Length -lt 1000000) {
    throw "Noto Sans portable tampak tidak lengkap."
}

$env:QT_QPA_PLATFORM = "offscreen"
python -m pytest -q
Assert-NativeSuccess "Regression + real FFmpeg test suite"

python "$Root\build\generate_icon.py"
Assert-NativeSuccess "Generate icon"
python -m PyInstaller --noconfirm --clean --windowed --onedir --name "Full Album Maker" --icon "$Root\assets\logo.ico" --paths "$Root\src" "$Root\src\full_album_maker\main.py"
Assert-NativeSuccess "Build PyInstaller"

$App = "$Root\dist\Full Album Maker"
if (-not (Test-Path "$App\Full Album Maker.exe")) {
    throw "Build PyInstaller selesai tanpa menghasilkan Full Album Maker.exe."
}
New-Item -ItemType Directory -Force "$App\tools\ffmpeg" | Out-Null
Copy-Item "$Root\tools\ffmpeg\ffmpeg.exe" "$App\tools\ffmpeg\ffmpeg.exe" -Force
Copy-Item "$Root\tools\ffmpeg\ffprobe.exe" "$App\tools\ffmpeg\ffprobe.exe" -Force
Copy-Item "$Root\LICENSE" "$App\LICENSE.txt" -Force
Copy-Item "$Root\THIRD_PARTY_NOTICES.md" "$App\THIRD_PARTY_NOTICES.md" -Force
New-Item -ItemType Directory -Force "$App\assets\fonts" | Out-Null
Copy-Item "$Root\assets\logo.svg" "$App\assets\logo.svg" -Force
Copy-Item "$Root\assets\fonts\fonts.conf" "$App\assets\fonts\fonts.conf" -Force
Copy-Item "$Root\assets\fonts\NotoSans.ttf" "$App\assets\fonts\NotoSans.ttf" -Force
Copy-Item "$Root\assets\fonts\NotoSans-OFL.txt" "$App\assets\fonts\NotoSans-OFL.txt" -Force

$FfLicense = Get-ChildItem ffmpeg_unpack -Recurse -File | Where-Object { $_.Name -eq "LICENSE.txt" } | Select-Object -First 1
$FfReadme = Get-ChildItem ffmpeg_unpack -Recurse -File | Where-Object { $_.Name -eq "README.txt" } | Select-Object -First 1
if ($FfLicense) { Copy-Item $FfLicense.FullName "$App\FFMPEG-LICENSE.txt" -Force }
if ($FfReadme) { Copy-Item $FfReadme.FullName "$App\FFMPEG-README.txt" -Force }

New-Item -ItemType Directory -Force "$App\data" | Out-Null
New-Item -ItemType Directory -Force "$App\temp" | Out-Null
New-Item -ItemType Directory -Force "$App\output" | Out-Null
python "$Root\build\write_release_capabilities.py" --root "$App"
Assert-NativeSuccess "Tulis CAPABILITIES.json"

$Zip = "$Root\$ReleaseZipName"
if (Test-Path $Zip) { Remove-Item $Zip -Force }
Compress-Archive -Path "$App" -DestinationPath $Zip
if (-not (Test-Path $Zip)) { throw "Portable ZIP tidak berhasil dibuat." }

$SmokeRoot = Join-Path $Root "portable smoke – O'Brien"
if (Test-Path $SmokeRoot) { Remove-Item $SmokeRoot -Recurse -Force }
Expand-Archive $Zip -DestinationPath $SmokeRoot
$SmokeApp = Get-ChildItem $SmokeRoot -Recurse -Filter "Full Album Maker.exe" | Select-Object -First 1
if (-not $SmokeApp) { throw "EXE portable tidak ditemukan setelah extract." }

$SavedGemini = $env:GEMINI_API_KEY
$SavedGoogle = $env:GOOGLE_API_KEY
$SavedPythonHome = $env:PYTHONHOME
$SavedPythonPath = $env:PYTHONPATH
try {
    $env:GEMINI_API_KEY = $null
    $env:GOOGLE_API_KEY = $null
    $env:PYTHONHOME = $null
    $env:PYTHONPATH = $null
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"

    if (Get-Command python -ErrorAction SilentlyContinue) {
        throw "Smoke lokal gagal mengisolasi Python global."
    }
    if (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
        throw "Smoke lokal gagal mengisolasi FFmpeg global."
    }

    $SmokeProcess = Start-Process -FilePath $SmokeApp.FullName -ArgumentList "--portable-smoke" -Wait -PassThru
    if ($SmokeProcess.ExitCode -ne 0) {
        throw "Portable smoke keluar dengan kode $($SmokeProcess.ExitCode)."
    }
}
finally {
    $env:PATH = $OldPathForBuild
    $env:GEMINI_API_KEY = $SavedGemini
    $env:GOOGLE_API_KEY = $SavedGoogle
    $env:PYTHONHOME = $SavedPythonHome
    $env:PYTHONPATH = $SavedPythonPath
}

$SmokeReport = Join-Path $SmokeApp.DirectoryName "temp\portable-smoke.json"
if (-not (Test-Path $SmokeReport)) { throw "portable-smoke.json tidak dibuat." }
$Smoke = Get-Content $SmokeReport -Raw | ConvertFrom-Json
if (-not $Smoke.ok -or $Smoke.api_key_present) {
    throw "Portable smoke report tidak memenuhi kontrak offline."
}
if ($Smoke.output_streams -notcontains "audio" -or $Smoke.output_streams -notcontains "video") {
    throw "Portable smoke output belum terverifikasi audio+video."
}
if ($Smoke.gui_title -notlike "*v$Version*") {
    throw "GUI portable tidak menampilkan versi release $Version. Title: $($Smoke.gui_title)"
}

Write-Host "Full Album Maker v$Version"
Write-Host "Portable ZIP siap di: $Zip"
Write-Host "SHA-256: $((Get-FileHash $Zip -Algorithm SHA256).Hash.ToLowerInvariant())"
Write-Host "Smoke portable: OK ($($Smoke.output_duration_seconds)s; $($Smoke.output_bytes) bytes; $($Smoke.output_streams -join ', '))"