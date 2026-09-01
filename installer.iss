; Inno Setup Script for Mixed in P
; Requires Inno Setup 6.x — https://jrsoftware.org/isinfo.php

#define MyAppName "Mixed in P"
#define MyAppVersion "1.5.1"
#define MyAppPublisher "Jared P"
#define MyAppExeName "MixedInP.exe"

[Setup]
AppId={{E3F7A1B2-5C4D-4E6F-8A9B-1C2D3E4F5A6B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\MixedInP
DefaultGroupName={#MyAppName}
LicenseFile=LICENSE
OutputDir=dist
; Stable, version-less filename so the GitHub
; releases/latest/download/MixedInP-Setup.exe link always resolves. The
; version lives in the release tag (vX.Y.Z), not the filename.
OutputBaseFilename=MixedInP-Setup
SetupIconFile=resources\icon.ico
UninstallDisplayIcon={app}\MixedInP.exe
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Windows 10 2004 (build 19041) and up. Without this Inno applies its own
; default, which still permits Windows 7 SP1 — where the bundle cannot run at
; all, so the install completed and the app then failed at launch with a DLL
; error. A refusal from the installer is the better failure.
;
; 19041 rather than 19045: 20H1 through 22H2 all share the 19041 kernel and
; differ only by enablement package, so this admits the whole 22H2 family —
; which is the only Windows 10 still receiving updates at its EOL, i.e. the
; only one a real user is realistically on.
MinVersion=10.0.19041
DisableProgramGroupPage=yes
WizardImageFile=resources\installer_wizard.png
WizardSmallImageFile=resources\installer_p_logo.png
; Tells Explorer to refresh its association cache when [Registry] changes
; land. Without it the "Open with" entry can take a logoff to appear.
ChangesAssociations=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\MixedInP\MixedInP.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\MixedInP\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; --- "Open with Mixed in P" ----------------------------------------------
; HKA resolves to HKLM for an admin install (the default here, since
; DefaultDirName is {autopf}) and to HKCU otherwise. Never hardcode HKLM.
;
; This buys presence in the Open with submenu only. Windows 10/11 does not
; let an installer take a file type's *default* silently — attempting it gets
; the association reset. Becoming the default is user-driven; see the
; Capabilities block below, which is what makes that a single journey.
Root: HKA; Subkey: "Software\Classes\MixedInP.Audio"; ValueType: string; ValueData: "Audio File"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\MixedInP.Audio\DefaultIcon"; ValueType: string; ValueData: "{app}\{#MyAppExeName},0"
; %1 quoted exactly so paths with spaces arrive as one argument.
Root: HKA; Subkey: "Software\Classes\MixedInP.Audio\shell\open\command"; ValueType: string; ValueData: """{app}\{#MyAppExeName}"" ""%1"""

; One entry per type the GUI accepts (src/gui/widgets/drop_zone.py).
Root: HKA; Subkey: "Software\Classes\.mp3\OpenWithProgids"; ValueType: string; ValueName: "MixedInP.Audio"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.wav\OpenWithProgids"; ValueType: string; ValueName: "MixedInP.Audio"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.flac\OpenWithProgids"; ValueType: string; ValueName: "MixedInP.Audio"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.aiff\OpenWithProgids"; ValueType: string; ValueName: "MixedInP.Audio"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.aif\OpenWithProgids"; ValueType: string; ValueName: "MixedInP.Audio"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.m4a\OpenWithProgids"; ValueType: string; ValueName: "MixedInP.Audio"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.ogg\OpenWithProgids"; ValueType: string; ValueName: "MixedInP.Audio"; ValueData: ""; Flags: uninsdeletevalue

; --- Default apps: one grouped entry, not seven separate journeys --------
; Without Capabilities + RegisteredApplications the user must hunt each
; extension individually in Settings. With it, Windows lists Mixed in P once
; with its file types grouped, so they set them from a single screen.
Root: HKA; Subkey: "Software\MixedInP"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\MixedInP\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "{#MyAppName}"
Root: HKA; Subkey: "Software\MixedInP\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "Harmonic-mixing analysis and player for DJs"
Root: HKA; Subkey: "Software\MixedInP\Capabilities"; ValueType: string; ValueName: "ApplicationIcon"; ValueData: "{app}\{#MyAppExeName},0"
Root: HKA; Subkey: "Software\MixedInP\Capabilities\FileAssociations"; ValueType: string; ValueName: ".mp3"; ValueData: "MixedInP.Audio"
Root: HKA; Subkey: "Software\MixedInP\Capabilities\FileAssociations"; ValueType: string; ValueName: ".wav"; ValueData: "MixedInP.Audio"
Root: HKA; Subkey: "Software\MixedInP\Capabilities\FileAssociations"; ValueType: string; ValueName: ".flac"; ValueData: "MixedInP.Audio"
Root: HKA; Subkey: "Software\MixedInP\Capabilities\FileAssociations"; ValueType: string; ValueName: ".aiff"; ValueData: "MixedInP.Audio"
Root: HKA; Subkey: "Software\MixedInP\Capabilities\FileAssociations"; ValueType: string; ValueName: ".aif"; ValueData: "MixedInP.Audio"
Root: HKA; Subkey: "Software\MixedInP\Capabilities\FileAssociations"; ValueType: string; ValueName: ".m4a"; ValueData: "MixedInP.Audio"
Root: HKA; Subkey: "Software\MixedInP\Capabilities\FileAssociations"; ValueType: string; ValueName: ".ogg"; ValueData: "MixedInP.Audio"
Root: HKA; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: "Software\MixedInP\Capabilities"; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
