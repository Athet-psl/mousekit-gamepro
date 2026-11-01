; Inno Setup script: dist\mousekit-setup-VERSION.exe, a per-user install (no admin rights needed).
; Built by packaging\windows\build.ps1: iscc /DVersion=X /DSource=dist\Mousekit mousekit.iss

#ifndef Version
  #define Version "0.0.0"
#endif
#ifndef Source
  #define Source "..\..\dist\Mousekit"
#endif

[Setup]
AppId={{6B0F6C1E-8E59-4C4B-9A43-4D6F75B1A7C2}
AppName=Mousekit for GamePro
AppVersion={#Version}
AppVerName=Mousekit for GamePro {#Version}
AppPublisher=Athet-psl
AppPublisherURL=https://github.com/Athet-psl/mousekit-gamepro
AppSupportURL=https://github.com/Athet-psl/mousekit-gamepro/issues
DefaultDirName={localappdata}\Programs\Mousekit
DefaultGroupName=Mousekit for GamePro
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
OutputBaseFilename=mousekit-setup-{#Version}
SetupIconFile=..\..\data\mousekit.ico
UninstallDisplayIcon={app}\mousekit.exe
LicenseFile=..\..\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "service"; Description: "Start the Mousekit service at sign-in (needed for button actions, gestures and effects)"
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; Flags: unchecked

[Files]
Source: "{#Source}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Mousekit for GamePro"; Filename: "{app}\mousekit.exe"
Name: "{autodesktop}\Mousekit for GamePro"; Filename: "{app}\mousekit.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Mousekit"; \
  ValueData: """{app}\mousekitd.exe"""; Flags: uninsdeletevalue; Tasks: service

[Run]
Filename: "{app}\mousekitd.exe"; Flags: nowait; Tasks: service
; An update started from the app (/UPDATE=1): open it again on its About page.
Filename: "{app}\mousekit.exe"; Parameters: "--about"; Flags: nowait; Check: IsUpdate
Filename: "{app}\mousekit.exe"; Description: "Open Mousekit"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM mousekitd.exe"; Flags: runhidden; RunOnceId: "StopService"

[Code]
procedure StopService();
var
  Code: Integer;
begin
  { The service keeps its files open: stop it before they are replaced. }
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM mousekitd.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

function IsUpdate(): Boolean;
begin
  Result := ExpandConstant('{param:UPDATE|0}') = '1';
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopService();
  Result := '';
end;
