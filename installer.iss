; Inno Setup Script for Mixed in P
; Requires Inno Setup 6.x — https://jrsoftware.org/isinfo.php

#define MyAppName "Mixed in P"
#define MyAppVersion "1.3.0"
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
DisableProgramGroupPage=yes
WizardImageFile=resources\installer_wizard.png
WizardSmallImageFile=resources\installer_p_logo.png

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

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
