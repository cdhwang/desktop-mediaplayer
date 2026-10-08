<#
.SYNOPSIS
    Register Desktop Music as a handler for its supported media file types
    on Windows (per-user, no admin rights required).

.DESCRIPTION
    Writes a ProgID under HKCU:\Software\Classes that launches the app via the
    project's virtualenv `pythonw.exe` (no console window, no `uv run` cost),
    then lists the ProgID as an "Open with" candidate for every supported
    extension. Windows 8+ deliberately prevents apps from silently stealing the
    *default* association, so after running this you still pick "Desktop Music"
    once via the Open-with dialog or Settings > Apps > Default apps.

.NOTES
    Run from the project root:
        powershell -ExecutionPolicy Bypass -File .\scripts\register_windows.ps1

    Undo with:
        powershell -ExecutionPolicy Bypass -File .\scripts\unregister_windows.ps1
#>

[CmdletBinding()]
param(
    # Project root (defaults to the parent of this script's folder).
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),

    # ProgID: a unique identifier for this application's file class.
    [string]$ProgId = "DesktopMusic.MediaFile",

    [string]$FriendlyName = "Desktop Music"
)

$ErrorActionPreference = "Stop"

# --- locate the launcher (virtualenv pythonw.exe) and entry script ----------
$PythonW = Join-Path $ProjectRoot ".venv\Scripts\pythonw.exe"
$MainPy  = Join-Path $ProjectRoot "main.py"
$IconIco = Join-Path $ProjectRoot "src\desktop_music\resources\app_icon.ico"

if (-not (Test-Path $PythonW)) {
    throw "pythonw.exe not found at '$PythonW'. Create the venv first (e.g. 'uv sync')."
}
if (-not (Test-Path $MainPy)) {
    throw "main.py not found at '$MainPy'. Is -ProjectRoot correct?"
}

# "%1" is substituted by Windows with the double-clicked file path.
$Command = "`"$PythonW`" `"$MainPy`" `"%1`""
Write-Host "Launcher command: $Command"

# --- supported extensions (keep in sync with constants.py) ------------------
$Extensions = @(
    # audio
    ".mp3", ".flac", ".wav", ".ape", ".m4a", ".aac", ".ogg", ".opus",
    ".wma", ".wv", ".tta", ".alac", ".aiff", ".aif",
    # video
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v",
    ".mpg", ".mpeg"
)

$ClassesRoot = "HKCU:\Software\Classes"

# --- 1. create the ProgID ---------------------------------------------------
$progKey = Join-Path $ClassesRoot $ProgId
New-Item -Path $progKey -Force | Out-Null
Set-ItemProperty -Path $progKey -Name "(default)" -Value $FriendlyName

# DefaultIcon
$iconKey = Join-Path $progKey "DefaultIcon"
New-Item -Path $iconKey -Force | Out-Null
if (Test-Path $IconIco) {
    Set-ItemProperty -Path $iconKey -Name "(default)" -Value "`"$IconIco`",0"
} else {
    # fall back to the launcher's own icon
    Set-ItemProperty -Path $iconKey -Name "(default)" -Value "`"$PythonW`",0"
    Write-Warning "app_icon.ico not found; using pythonw.exe icon."
}

# shell\open\command
$cmdKey = Join-Path $progKey "shell\open\command"
New-Item -Path $cmdKey -Force | Out-Null
Set-ItemProperty -Path $cmdKey -Name "(default)" -Value $Command

Write-Host "Created ProgID '$ProgId'."

# --- 2. register ProgID as an Open-With candidate for each extension ---------
foreach ($ext in $Extensions) {
    $extKey = Join-Path $ClassesRoot ($ext + "\OpenWithProgids")
    New-Item -Path $extKey -Force | Out-Null
    # empty REG_NONE value is the documented convention here
    New-ItemProperty -Path $extKey -Name $ProgId -PropertyType None `
        -Value ([byte[]]@()) -Force | Out-Null
}
Write-Host ("Registered as 'Open with' candidate for {0} extensions." -f $Extensions.Count)

# --- 3. notify the shell so changes take effect without a reboot ------------
$sig = @'
[System.Runtime.InteropServices.DllImport("shell32.dll")]
public static extern void SHChangeNotify(int eventId, int flags, System.IntPtr item1, System.IntPtr item2);
'@
$shell = Add-Type -MemberDefinition $sig -Name "ShellNotify" -Namespace "Win32" -PassThru
# SHCNE_ASSOCCHANGED = 0x08000000, SHCNF_IDLIST = 0x0000
$shell::SHChangeNotify(0x08000000, 0x0000, [System.IntPtr]::Zero, [System.IntPtr]::Zero)

Write-Host ""
Write-Host "Done. To make Desktop Music the DEFAULT for a type:" -ForegroundColor Green
Write-Host "  - Right-click a media file > Open with > Choose another app > Desktop Music > Always"
Write-Host "  - or Settings > Apps > Default apps > choose by file type"
