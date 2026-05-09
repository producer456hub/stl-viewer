# STL Viewer

A tiny local web app for browsing and renaming all the `.stl` files on your disk. Scans the drive once, then lets you flick through previews with the arrow keys and rename files in place.

![arrow keys to scroll, type a new name to rename](https://img.shields.io/badge/platform-windows-blue) ![python](https://img.shields.io/badge/python-3.8%2B-blue)

## Features

- 3D preview of every `.stl` (three.js + STLLoader, orbit/zoom/pan)
- Arrow keys to step through, Home/End to jump to ends
- Rename in place — edits the actual file on disk
- "Show in Folder" copies the containing folder path to clipboard
- "Rescan Disk" re-walks `C:\` without restarting the server
- Delete (or `Del` key) sends the file to the Recycle Bin

## Setup

Requires Python 3.8+ (uses only the standard library) and PowerShell (used for the disk scan on Windows).

```powershell
# 1. Initial scan — produces stl_files.txt
Get-ChildItem -Path C:\ -Filter *.stl -Recurse -File -ErrorAction SilentlyContinue `
  | Select-Object -ExpandProperty FullName `
  | Out-File -FilePath stl_files.txt -Encoding utf8

# 2. Run the viewer (auto-opens browser at http://127.0.0.1:8765/)
python server.py
```

Subsequent rescans can be triggered from the **Rescan Disk** button in the UI.

### Optional: Desktop shortcut (Windows)

```powershell
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut("$([Environment]::GetFolderPath('Desktop'))\STL Viewer.lnk")
$sc.TargetPath = (Get-Command python.exe).Source
$sc.Arguments = '"' + (Resolve-Path .\server.py).Path + '"'
$sc.WorkingDirectory = (Get-Location).Path
$sc.WindowStyle = 7  # minimized
$sc.IconLocation = "C:\Windows\System32\shell32.dll,15"
$sc.Save()
```

## Controls

| Key | Action |
| --- | --- |
| ← / → / ↑ / ↓ / PageUp / PageDown | Previous / next model |
| Home / End | First / last model |
| Mouse drag | Orbit |
| Scroll | Zoom |
| Right-drag | Pan |
| Type filename + Enter | Rename file on disk |
| Del | Send file to Recycle Bin (with confirm) |

## Adapting to other platforms

`server.py` is plain Python and runs anywhere. The disk scan uses PowerShell, so on macOS/Linux replace it with e.g.:

```bash
find / -name '*.stl' 2>/dev/null > stl_files.txt
```

The rescan endpoint in `server.py` shells out to `powershell.exe` — swap it for `find` if porting.

## License

MIT
