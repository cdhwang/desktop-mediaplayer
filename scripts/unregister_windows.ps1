<#
.SYNOPSIS
    Undo register_windows.ps1: remove the Desktop Music ProgID and its
    "Open with" candidate entries (per-user).

.NOTES
    Run from the project root:
        powershell -ExecutionPolicy Bypass -File .\scripts\unregister_windows.ps1
#>

[CmdletBinding()]
param(
    [string]$ProgId = "DesktopMusic.MediaFile"
)

$ErrorActionPreference = "Stop"

$Extensions = @(
    ".mp3", ".flac", ".wav", ".ape", ".m4a", ".aac", ".ogg", ".opus",
    ".wma", ".wv", ".tta", ".alac", ".aiff", ".aif",
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v",
    ".mpg", ".mpeg"
)

$ClassesRoot = "HKCU:\Software\Classes"

# 1. remove the ProgID key
$progKey = Join-Path $ClassesRoot $ProgId
if (Test-Path $progKey) {
    Remove-Item -Path $progKey -Recurse -Force
    Write-Host "Removed ProgID '$ProgId'."
} else {
    Write-Host "ProgID '$ProgId' not present."
}

# 2. remove the OpenWithProgids candidate value from each extension
foreach ($ext in $Extensions) {
    $owKey = Join-Path $ClassesRoot ($ext + "\OpenWithProgids")
    if (Test-Path $owKey) {
        $prop = Get-ItemProperty -Path $owKey -Name $ProgId -ErrorAction SilentlyContinue
        if ($null -ne $prop) {
            Remove-ItemProperty -Path $owKey -Name $ProgId -ErrorAction SilentlyContinue
            Write-Host "Cleared candidate for $ext"
        }
    }
}

# 3. refresh the shell
$sig = @'
[System.Runtime.InteropServices.DllImport("shell32.dll")]
public static extern void SHChangeNotify(int eventId, int flags, System.IntPtr item1, System.IntPtr item2);
'@
$shell = Add-Type -MemberDefinition $sig -Name "ShellNotify" -Namespace "Win32" -PassThru
$shell::SHChangeNotify(0x08000000, 0x0000, [System.IntPtr]::Zero, [System.IntPtr]::Zero)

Write-Host "Done."
Write-Host "Note: if you had set Desktop Music as a *default* for some types," -ForegroundColor Yellow
Write-Host "Windows may still show it until you pick another default in Settings." -ForegroundColor Yellow
