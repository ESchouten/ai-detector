; Per-user installation preserves Windows ML's user context and personal recordings.
[Setup]
AppId={{75C89A08-EA31-45C5-A480-E6C3029A6517}
AppName=AI Detector
AppVersion={#Version}
AppPublisher=AI Detector
AppPublisherURL=https://github.com/ESchouten/ai-detector
DefaultDirName={localappdata}\Programs\AI Detector
DefaultGroupName=AI Detector
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible and not arm64
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.26100
OutputDir={#OutputDir}
OutputBaseFilename=AI-Detector-{#Version}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\AI Detector.exe
#ifdef Signed
SignTool=release
SignedUninstaller=yes
#endif

[Tasks]
Name: startup; Description: "Open AI Detector when I sign in (recommended)"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\AI Detector"; Filename: "{app}\AI Detector.exe"
Name: "{group}\Quit AI Detector"; Filename: "{app}\AI Detector.exe"; Parameters: "--quit"
Name: "{group}\Uninstall AI Detector"; Filename: "{uninstallexe}"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "AI Detector"; ValueData: """{app}\AI Detector.exe"""; Tasks: startup; Flags: uninsdeletevalue

[Run]
Filename: "{app}\AI Detector.exe"; Description: "Open AI Detector"; Flags: nowait postinstall skipifsilent

[Code]
function CloseDetector(): Boolean;
var
  ExitCode: Integer;
  Executable: String;
begin
  Executable := ExpandConstant('{app}\AI Detector.exe');
  Result := not FileExists(Executable);
  if not Result then
    Result := Exec(Executable, '--quit', '', SW_HIDE, ewWaitUntilTerminated, ExitCode) and (ExitCode = 0);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if not CloseDetector() then
    Result := 'AI Detector could not finish shutting down. Close it and retry. Your settings and recordings have not been removed.';
end;

function InitializeUninstall(): Boolean;
begin
  Result := CloseDetector();
  if not Result then
    MsgBox('AI Detector is still finishing work. Close it and retry uninstalling. Your settings and recordings have not been removed.', mbError, MB_OK);
end;
