; Per-user installation preserves Windows ML's user context and personal recordings.
#define StartupDescription "Start AI Detector when I sign in (recommended)"
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
SetupIconFile=artwork\app.ico
WizardImageFile=artwork\wizard.bmp
WizardSmallImageFile=artwork\wizard-small.bmp
DisableWelcomePage=yes
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
UsePreviousTasks=no
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\AI Detector.exe
#ifdef Signed
SignTool=release
SignedUninstaller=yes
#endif

[Tasks]
; Conditional entries set the default before Inno applies explicit /TASKS choices.
Name: startup; Description: "{#StartupDescription}"; Check: StartAtLoginByDefault
Name: startup; Description: "{#StartupDescription}"; Check: not StartAtLoginByDefault; Flags: unchecked

[Messages]
WizardSelectTasks=Install AI Detector
SelectTasksDesc=Your cameras and alerts will be set up in your browser.
SelectTasksLabel2=Click Install to get started.%n%nAI Detector can open automatically when you sign in, so your dashboard is ready and enabled monitoring resumes.%n%nYou can change this later from the AI Detector icon beside the clock.
WizardInstalling=Installing AI Detector
InstallingLabel=Getting AI Detector ready on your computer.
FinishedHeadingLabel=You're ready to set up your cameras
FinishedLabel=AI Detector is installed.%n%nOpen it to follow the guided setup in your browser. You can close the browser while monitoring continues.%n%nTo return later, use AI Detector in the Start menu or its icon beside the clock.
ButtonFinish=&Finish

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Excludes: "START HERE.txt"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\AI Detector"; Filename: "{app}\AI Detector.exe"
Name: "{group}\Quit AI Detector"; Filename: "{app}\AI Detector.exe"; Parameters: "--quit"
Name: "{group}\Uninstall AI Detector"; Filename: "{uninstallexe}"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "AI Detector"; ValueData: """{app}\AI Detector.exe"""; Tasks: startup
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "AI Detector"; Tasks: not startup; Flags: deletevalue
; Also remove startup if the user enabled it from the tray after installation.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "AI Detector"; Flags: uninsdeletevalue

[Run]
Filename: "{app}\AI Detector.exe"; Description: "Open AI Detector"; Flags: nowait postinstall skipifsilent

[Code]
function StartAtLoginByDefault(): Boolean;
begin
  { Upgrades preserve the preference changed through the tray, including opting out. }
  Result := not FileExists(ExpandConstant('{app}\AI Detector.exe')) or
    RegValueExists(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'AI Detector');
end;

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
