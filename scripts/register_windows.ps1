<#
.SYNOPSIS
    Register Desktop Music (installed via `uv tool install --editable .`) as a
    handler for its supported media file types on Windows (per-user, no admin
    rights), with a friendly "Desktop Music" name in the Open-with dialog and
    the app's own media-file icons in File Explorer.

.DESCRIPTION
    This script targets the launcher that `uv tool install` creates
    (desktop-music.exe). Because that launcher's file name is what the
    Open-with dialog shows by default, we register an application entry with a
    FriendlyAppName so the dialog reads "Desktop Music" instead.

    It writes, under HKCU:\Software\Classes:
      * Applications\desktop-music.exe
            FriendlyAppName        = "Desktop Music"
            DefaultIcon            = app_icon.ico
            shell\open\command     = "<launcher>" "%1"
        -> this is what makes the Open-with dialog show the friendly name.
      * DesktopMusic.AudioFile / DesktopMusic.VideoFile ProgIDs
            each with its own DefaultIcon (file_audio.ico / file_video.ico)
            and the same open command.
      * For every supported extension:
            - OpenWithProgids   += the matching ProgID
            - OpenWithList      += desktop-music.exe  (friendly-named entry)
            - DefaultIcon        = our media icon (Explorer icon up front)

    Icon/default caveats:
      * If an extension already has a per-user "UserChoice" default, Windows
        honors that association's icon and app. Pick Desktop Music as the
        default for the type (hint printed at the end) to override it.
      * Windows 8+ prevents apps from silently stealing the *default*
        association, so double-click opening still requires choosing Desktop
        Music once.

.NOTES
    Prereq:  uv tool install --editable .
    Run from the project root:
        powershell -ExecutionPolicy Bypass -File .\scripts\register_windows.ps1

    Undo with:
        powershell -ExecutionPolicy Bypass -File .\scripts\unregister_windows.ps1
#>

[CmdletBinding()]
param(
    # Project root (resolved below so it works even when $PSScriptRoot is
    # empty, e.g. the script dot-sourced or piped into a console).
    [string]$ProjectRoot,

    # ProgIDs for the audio/video classes (carry the per-type icons).
    [string]$AudioProgId = "DesktopMusic.AudioFile",
    [string]$VideoProgId = "DesktopMusic.VideoFile",

    # Friendly name shown in the Open-with dialog and Default Apps.
    [string]$FriendlyName = "Desktop Music",

    # Explicit path to the uv-installed launcher; auto-detected when omitted.
    [string]$LauncherPath = ""
)

$ErrorActionPreference = "Stop"

# Resolve the project root with graceful fallbacks:
#   $PSScriptRoot -> $MyInvocation.MyCommand.Path -> current directory.
if (-not $ProjectRoot) {
    $scriptDir = $PSScriptRoot
    if (-not $scriptDir -and $MyInvocation.MyCommand.Path) {
        $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    }
    if ($scriptDir) {
        $ProjectRoot = Split-Path -Parent $scriptDir
    } else {
        $ProjectRoot = (Get-Location).Path
    }
}
Write-Host "ProjectRoot: $ProjectRoot"

$ResDir   = Join-Path $ProjectRoot "src\desktop_music\resources"
$AudioIco = Join-Path $ResDir "file_audio.ico"
$VideoIco = Join-Path $ResDir "file_video.ico"
$AppIco   = Join-Path $ResDir "app_icon.ico"

# --- locate the uv-installed launcher (desktop-music.exe) -------------------
function Find-Launcher {
    if ($LauncherPath -and (Test-Path $LauncherPath)) { return $LauncherPath }

    $candidates = @()
    # 1. Anything already on PATH (uv puts its bin dir there).
    $cmd = Get-Command "desktop-music" -ErrorAction SilentlyContinue
    if ($cmd) { $candidates += $cmd.Source }
    # 2. uv's default tool-bin directory.
    $candidates += (Join-Path $env:USERPROFILE ".local\bin\desktop-music.exe")
    if ($env:UV_TOOL_BIN_DIR) {
        $candidates += (Join-Path $env:UV_TOOL_BIN_DIR "desktop-music.exe")
    }
    # 3. uv tools install tree (per-tool venv Scripts dir).
    $toolsRoot = if ($env:UV_TOOL_DIR) { $env:UV_TOOL_DIR } `
                 else { Join-Path $env:APPDATA "uv\tools" }
    $candidates += (Join-Path $toolsRoot "desktop-music\Scripts\desktop-music.exe")

    foreach ($c in $candidates) {
        if ($c -and (Test-Path $c)) { return (Resolve-Path $c).Path }
    }
    return $null
}

$Launcher = Find-Launcher
if (-not $Launcher) {
    throw ("desktop-music.exe not found. Install it first with " +
           "'uv tool install --editable .', or pass -LauncherPath '<full path>'.")
}
$ExeName = Split-Path $Launcher -Leaf   # e.g. "desktop-music.exe"
Write-Host "Launcher: $Launcher"

# "%1" is substituted by Windows with the opened file path.
$Command = "`"$Launcher`" `"%1`""

# --- supported extensions (keep in sync with constants.py) ------------------
$AudioExtensions = @(
    ".mp3", ".flac", ".wav", ".ape", ".m4a", ".aac", ".ogg", ".opus",
    ".wma", ".wv", ".tta", ".alac", ".aiff", ".aif"
)
$VideoExtensions = @(
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v",
    ".mpg", ".mpeg"
)

$ClassesRoot = "HKCU:\Software\Classes"

function Resolve-Icon([string]$preferred) {
    if (Test-Path $preferred) { return $preferred }
    if (Test-Path $AppIco)    { return $AppIco }
    return $null
}
$AudioIconPath = Resolve-Icon $AudioIco
$VideoIconPath = Resolve-Icon $VideoIco
$AppIconPath   = if (Test-Path $AppIco) { $AppIco } else { $null }

# --- 1. the Application entry that gives the Open-with dialog a nice name ----
#     HKCU\Software\Classes\Applications\<exe> { FriendlyAppName, DefaultIcon,
#     shell\open\command }
$appKey = Join-Path $ClassesRoot ("Applications\" + $ExeName)
New-Item -Path $appKey -Force | Out-Null
Set-ItemProperty -Path $appKey -Name "FriendlyAppName" -Value $FriendlyName

$appIconKey = Join-Path $appKey "DefaultIcon"
New-Item -Path $appIconKey -Force | Out-Null
if ($AppIconPath) {
    Set-ItemProperty -Path $appIconKey -Name "(default)" -Value "`"$AppIconPath`",0"
} else {
    Set-ItemProperty -Path $appIconKey -Name "(default)" -Value "`"$Launcher`",0"
}

$appCmdKey = Join-Path $appKey "shell\open\command"
New-Item -Path $appCmdKey -Force | Out-Null
Set-ItemProperty -Path $appCmdKey -Name "(default)" -Value $Command

# Advertise which extensions this application supports (used by the dialog).
$appTypesKey = Join-Path $appKey "SupportedTypes"
New-Item -Path $appTypesKey -Force | Out-Null
foreach ($ext in ($AudioExtensions + $VideoExtensions)) {
    Set-ItemProperty -Path $appTypesKey -Name $ext -Value ""
}
Write-Host "Registered application '$ExeName' as '$FriendlyName'."

# --- helper: create one media ProgID (friendly name, per-type icon, command) -
function New-MediaProgId([string]$progId, [string]$label, [string]$iconPath) {
    $progKey = Join-Path $ClassesRoot $progId
    New-Item -Path $progKey -Force | Out-Null
    Set-ItemProperty -Path $progKey -Name "(default)" -Value $label

    $iconKey = Join-Path $progKey "DefaultIcon"
    New-Item -Path $iconKey -Force | Out-Null
    if ($iconPath) {
        Set-ItemProperty -Path $iconKey -Name "(default)" -Value "`"$iconPath`",0"
    } else {
        Set-ItemProperty -Path $iconKey -Name "(default)" -Value "`"$Launcher`",0"
        Write-Warning "No .ico found for $progId; using launcher icon."
    }

    $cmdKey = Join-Path $progKey "shell\open\command"
    New-Item -Path $cmdKey -Force | Out-Null
    Set-ItemProperty -Path $cmdKey -Name "(default)" -Value $Command
}

# --- helper: wire one extension (OpenWithProgids + OpenWithList + icon) ------
function Register-Extension([string]$ext, [string]$progId, [string]$iconPath) {
    # a) ProgID candidate (drives the per-type DefaultIcon once chosen).
    $owpKey = Join-Path $ClassesRoot ($ext + "\OpenWithProgids")
    New-Item -Path $owpKey -Force | Out-Null
    New-ItemProperty -Path $owpKey -Name $progId -PropertyType None `
        -Value ([byte[]]@()) -Force | Out-Null

    # b) Application candidate so the dialog lists the friendly-named launcher.
    $owlKey = Join-Path $ClassesRoot ($ext + "\OpenWithList")
    New-Item -Path $owlKey -Force | Out-Null
    Set-ItemProperty -Path $owlKey -Name $ExeName -Value ""

    # c) Per-extension DefaultIcon so Explorer shows our icon up front
    #    (unless a UserChoice default overrides the type).
    if ($iconPath) {
        $extIconKey = Join-Path $ClassesRoot ($ext + "\DefaultIcon")
        New-Item -Path $extIconKey -Force | Out-Null
        Set-ItemProperty -Path $extIconKey -Name "(default)" -Value "`"$iconPath`",0"
    }
}

# --- 2. create the media ProgIDs --------------------------------------------
New-MediaProgId $AudioProgId $FriendlyName $AudioIconPath
New-MediaProgId $VideoProgId $FriendlyName $VideoIconPath

# --- 3. register each extension ---------------------------------------------
foreach ($ext in $AudioExtensions) { Register-Extension $ext $AudioProgId $AudioIconPath }
foreach ($ext in $VideoExtensions) { Register-Extension $ext $VideoProgId $VideoIconPath }
Write-Host ("Registered {0} audio + {1} video extensions." -f `
    $AudioExtensions.Count, $VideoExtensions.Count)

# --- 4. notify the shell so changes take effect without a reboot ------------
$sig = @'
[System.Runtime.InteropServices.DllImport("shell32.dll")]
public static extern void SHChangeNotify(int eventId, int flags, System.IntPtr item1, System.IntPtr item2);
'@
$shell = Add-Type -MemberDefinition $sig -Name "ShellNotify" -Namespace "Win32" -PassThru
# SHCNE_ASSOCCHANGED = 0x08000000, SHCNF_IDLIST = 0x0000
$shell::SHChangeNotify(0x08000000, 0x0000, [System.IntPtr]::Zero, [System.IntPtr]::Zero)

Write-Host ""
Write-Host "Done. The Open-with dialog should now show '$FriendlyName'" -ForegroundColor Green
Write-Host "(instead of '$ExeName'), and Explorer should show the media icons." -ForegroundColor Green
Write-Host ""
Write-Host "To open on double-click, set '$FriendlyName' as the default for a type:" -ForegroundColor Green
Write-Host "  - Right-click a media file > Open with > Choose another app > $FriendlyName > Always"
Write-Host "  - or Settings > Apps > Default apps"
Write-Host ""
Write-Host "If an icon/name doesn't refresh, log off/on or restart Explorer." -ForegroundColor DarkGray
