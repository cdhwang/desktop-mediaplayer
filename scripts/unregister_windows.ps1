<#
.SYNOPSIS
    Undo register_windows.ps1: remove the Desktop Music application entry,
    audio/video ProgIDs, their Open-with candidate entries (OpenWithProgids
    and OpenWithList), and the per-extension DefaultIcon values (per-user).

.NOTES
    Run from the project root:
        powershell -ExecutionPolicy Bypass -File .\scripts\unregister_windows.ps1
#>

[CmdletBinding()]
param(
    [string]$AudioProgId = "DesktopMusic.AudioFile",
    [string]$VideoProgId = "DesktopMusic.VideoFile",
    # Legacy single ProgID from older versions of the register script.
    [string]$LegacyProgId = "DesktopMusic.MediaFile",
    # Launcher exe name used for the Applications\ entry + OpenWithList.
    [string]$ExeName = "desktop-music.exe"
)

$ErrorActionPreference = "Stop"

$AudioExtensions = @(
    ".mp3", ".flac", ".wav", ".ape", ".m4a", ".aac", ".ogg", ".opus",
    ".wma", ".wv", ".tta", ".alac", ".aiff", ".aif"
)
$VideoExtensions = @(
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v",
    ".mpg", ".mpeg"
)
$AllExtensions = $AudioExtensions + $VideoExtensions

$ClassesRoot = "HKCU:\Software\Classes"

# --- 1. remove the Application entry ----------------------------------------
$appKey = Join-Path $ClassesRoot ("Applications\" + $ExeName)
if (Test-Path $appKey) {
    Remove-Item -Path $appKey -Recurse -Force
    Write-Host "Removed application entry '$ExeName'."
} else {
    Write-Host "Application entry '$ExeName' not present."
}

# --- 2. remove the ProgID keys ----------------------------------------------
foreach ($progId in @($AudioProgId, $VideoProgId, $LegacyProgId)) {
    $progKey = Join-Path $ClassesRoot $progId
    if (Test-Path $progKey) {
        Remove-Item -Path $progKey -Recurse -Force
        Write-Host "Removed ProgID '$progId'."
    } else {
        Write-Host "ProgID '$progId' not present."
    }
}

# --- 3. clean each extension ------------------------------------------------
$ProgIds = @($AudioProgId, $VideoProgId, $LegacyProgId)
foreach ($ext in $AllExtensions) {
    # 3a. remove our ProgIDs from the OpenWithProgids candidate list
    $owpKey = Join-Path $ClassesRoot ($ext + "\OpenWithProgids")
    if (Test-Path $owpKey) {
        foreach ($progId in $ProgIds) {
            $prop = Get-ItemProperty -Path $owpKey -Name $progId -ErrorAction SilentlyContinue
            if ($null -ne $prop) {
                Remove-ItemProperty -Path $owpKey -Name $progId -ErrorAction SilentlyContinue
                Write-Host "Cleared Open-with ProgID '$progId' for $ext"
            }
        }
    }

    # 3b. remove our launcher from the OpenWithList
    $owlKey = Join-Path $ClassesRoot ($ext + "\OpenWithList")
    if (Test-Path $owlKey) {
        $prop = Get-ItemProperty -Path $owlKey -Name $ExeName -ErrorAction SilentlyContinue
        if ($null -ne $prop) {
            Remove-ItemProperty -Path $owlKey -Name $ExeName -ErrorAction SilentlyContinue
            Write-Host "Cleared Open-with list entry '$ExeName' for $ext"
        }
    }

    # 3c. remove the per-extension DefaultIcon we added
    $extIconKey = Join-Path $ClassesRoot ($ext + "\DefaultIcon")
    if (Test-Path $extIconKey) {
        Remove-Item -Path $extIconKey -Recurse -Force
        Write-Host "Removed DefaultIcon for $ext"
    }
}

# --- 4. refresh the shell ---------------------------------------------------
$sig = @'
[System.Runtime.InteropServices.DllImport("shell32.dll")]
public static extern void SHChangeNotify(int eventId, int flags, System.IntPtr item1, System.IntPtr item2);
'@
$shell = Add-Type -MemberDefinition $sig -Name "ShellNotify" -Namespace "Win32" -PassThru
$shell::SHChangeNotify(0x08000000, 0x0000, [System.IntPtr]::Zero, [System.IntPtr]::Zero)

Write-Host "Done."
Write-Host "Note: if you had set Desktop Music as a *default* for some types," -ForegroundColor Yellow
Write-Host "Windows may still show it until you pick another default in Settings." -ForegroundColor Yellow
