; Inno Setup script: wraps dist\Capption (PyInstaller onedir) into Capption-Setup-<ver>.exe.
;
;   "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" /DAppVersion=0.1.0 installer\capption.iss
;
; Per-user install (no admin prompt) into %LOCALAPPDATA%\Programs\Capption. Uninstall leaves
; downloaded models and settings in %LOCALAPPDATA%\Capption / %APPDATA%\Capption.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6E3B8A52-4C1D-4E8B-9C57-2B1F0A7D9C31}
AppName=Capption
AppVersion={#AppVersion}
AppPublisher=tomwright0
AppPublisherURL=https://github.com/tomwright0/capption
DefaultDirName={localappdata}\Programs\Capption
DefaultGroupName=Capption
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.20348
OutputDir=..\dist
OutputBaseFilename=Capption-Setup-{#AppVersion}
SetupIconFile=..\build\capption.ico
UninstallDisplayIcon={app}\Capption.exe
LicenseFile=..\LICENSE
Compression=lzma2/normal
SolidCompression=no
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked
Name: "startup"; Description: "Start Capption when I sign in"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"
Source: "..\dist\Capption\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Capption"; Filename: "{app}\Capption.exe"
Name: "{autodesktop}\Capption"; Filename: "{app}\Capption.exe"; Tasks: desktopicon
Name: "{userstartup}\Capption"; Filename: "{app}\Capption.exe"; Tasks: startup

[Run]
Filename: "{app}\Capption.exe"; Description: "Launch Capption"; Flags: nowait postinstall skipifsilent
; In-app updates run the installer with /SILENT /launch=1 and expect Capption to come back.
Filename: "{app}\Capption.exe"; Flags: nowait; Check: RelaunchAfterUpdate

[Code]
function RelaunchAfterUpdate: Boolean;
begin
  Result := WizardSilent and (ExpandConstant('{param:launch|0}') = '1');
end;
