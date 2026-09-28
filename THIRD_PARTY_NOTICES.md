# Third-party notices

## FFmpeg

Windows portable builds bundle the GPL static x86_64 variant from
BtbN/FFmpeg-Builds because Full Album Maker uses the libx264 and libx265
encoders. The FFmpeg executable and its codec libraries are separate third-party
software and are not covered by the MIT license of Full Album Maker.

S12 pins the release input used by CI as follows:

- Provider: `BtbN/FFmpeg-Builds`
- Release ID: `397659030`
- Asset ID: `592976307`
- Asset: `ffmpeg-n9.0-latest-win64-gpl-9.0.zip`
- SHA-256: `b745ed683204c8e154d627bf75f2e530b7b2eec51d14fabdc8771912423ba67e`

The upstream convenience filename contains `latest`, but the release workflow
verifies the exact SHA-256 above before extraction. Any upstream content change
therefore fails the build until this pin is intentionally reviewed and updated.
The portable folder also includes the license/readme files supplied with the
FFmpeg build when present. Source/build information is available from the FFmpeg
project and BtbN/FFmpeg-Builds.

## Noto Sans

The Windows portable build includes Noto Sans as its deterministic fallback font
for FFmpeg/fontconfig text rendering.

- Source: `google/fonts`
- Pinned commit: `23e54b51ddffbc7713c583748e3bd86f62b1fa4a`
- Source path: `ofl/notosans/NotoSans[wdth,wght].ttf`
- License: SIL Open Font License 1.1

The corresponding `NotoSans-OFL.txt` is included beside the font in the portable
folder. User-selected custom font files are not copied into a project
implicitly; users remain responsible for those custom assets and their licenses.

## PySide6 / Qt

The desktop UI uses PySide6 / Qt. Their licensing terms are separate from the
MIT license of Full Album Maker. S12 Windows builds pin PySide6 `6.11.2` in the
release lockfile. Review the applicable Qt/PySide licensing terms before
commercial redistribution.
