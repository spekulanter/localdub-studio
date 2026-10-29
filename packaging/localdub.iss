; LocalDub Studio installer (Inno Setup 6). Build with: uv run python packaging/build_release.py
; The build script copies tools\uv.exe next to this file and passes /DAppVersion=x.y.z.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "LocalDub Studio"
#define AppExe "{app}\.venv\Scripts\localdub-app.exe"
#define OllamaModel "translategemma:4b"

[Setup]
AppId={{6E0B8F6E-3B1D-4C52-9E0A-7C6F0B7D4A11}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=LocalDub Studio
AppMutex=LocalDubStudioRunning
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\release
OutputBaseFilename=LocalDub-Studio-{#AppVersion}-Setup
SetupIconFile=..\localdub\assets\localdub.ico
UninstallDisplayIcon={app}\localdub\assets\localdub.ico
UninstallDisplayName={#AppName}
InfoBeforeFile=setup-info.txt
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
CloseApplications=no
DiskSpanning=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Types]
Name: "full"; Description: "Full installation (all optional features)"
Name: "standard"; Description: "Standard installation"
Name: "custom"; Description: "Custom installation"; Flags: iscustom

[Components]
Name: "core"; Description: "LocalDub Studio"; Types: full standard custom; Flags: fixed
Name: "diarization"; Description: "Speaker detection (46 MB download, experimental)"; Types: full
Name: "experimental"; Description: "Speech removal and voice cloning (about 3 GB download, experimental)"; Types: full

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "models"; Description: "Download the speech and voice models now (about 3.4 GB)"; GroupDescription: "Downloads:"
Name: "ollamamodel"; Description: "Download the translation model {#OllamaModel} with Ollama (about 3.3 GB)"; GroupDescription: "Downloads:"

[Files]
Source: "..\localdub\*"; DestDir: "{app}\localdub"; Excludes: "__pycache__,*.pyc"; Flags: recursesubdirs ignoreversion; Components: core
Source: "..\frontend\dist\*"; DestDir: "{app}\frontend\dist"; Flags: recursesubdirs ignoreversion; Components: core
Source: "..\pyproject.toml"; DestDir: "{app}"; Flags: ignoreversion; Components: core
Source: "..\uv.lock"; DestDir: "{app}"; Flags: ignoreversion; Components: core
Source: "..\.python-version"; DestDir: "{app}"; Flags: ignoreversion; Components: core
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion; Components: core
Source: "..\docs\LICENSES.md"; DestDir: "{app}\docs"; Flags: ignoreversion; Components: core
Source: "..\docs\QUALITY.md"; DestDir: "{app}\docs"; Flags: ignoreversion; Components: core
Source: "tools\uv.exe"; DestDir: "{app}\tools"; Flags: ignoreversion; Components: core
Source: "THIRD-PARTY-uv.txt"; DestDir: "{app}\tools"; Flags: ignoreversion; Components: core

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{#AppExe}"; WorkingDir: "{app}"; IconFilename: "{app}\localdub\assets\localdub.ico"
Name: "{autodesktop}\{#AppName}"; Filename: "{#AppExe}"; WorkingDir: "{app}"; IconFilename: "{app}\localdub\assets\localdub.ico"; Tasks: desktopicon

[Run]
Filename: "{#AppExe}"; WorkingDir: "{app}"; Description: "Start {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\localdub"
Type: filesandordirs; Name: "{app}\frontend"
Type: filesandordirs; Name: "{app}\tools"
Type: files; Name: "{app}\install.log"

[Code]
var
  ProgressPage: TOutputMarqueeProgressWizardPage;
  Problems: String;

function WebView2Present: Boolean;
var
  Version: String;
begin
  Result :=
    (RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0')) or
    (RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0'));
end;

function RunHidden(const CommandLine: String; var ResultCode: Integer): Boolean;
begin
  { cmd /S /C "<command line>" lets the command line contain quoted paths and redirections. }
  Result := Exec(ExpandConstant('{cmd}'), '/S /C "' + CommandLine + '"', ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function ToolOnPath(const Name: String): Boolean;
var
  Code: Integer;
begin
  Result := Exec(ExpandConstant('{cmd}'), '/S /C "where ' + Name + ' >nul 2>nul"', '', SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0);
end;

function WingetAvailable: Boolean;
begin
  Result := ToolOnPath('winget');
end;

function OllamaExe: String;
begin
  Result := ExpandConstant('{localappdata}\Programs\Ollama\ollama.exe');
  if not FileExists(Result) then
    Result := 'ollama';
end;

function FfmpegPresent: Boolean;
begin
  Result := ToolOnPath('ffmpeg') or FileExists(ExpandConstant('{localappdata}\Microsoft\WinGet\Links\ffmpeg.exe'));
end;

function OllamaPresent: Boolean;
begin
  Result := ToolOnPath('ollama') or FileExists(ExpandConstant('{localappdata}\Programs\Ollama\ollama.exe'));
end;

procedure InstallWithWinget(const Title, Id, Source: String);
var
  Code: Integer;
begin
  if WizardSilent then
  begin
    Problems := Problems + #13#10 + '- ' + Title + ' is not installed (silent setup does not install it).';
    Exit;
  end;
  if not WingetAvailable then
  begin
    MsgBox(Title + ' is needed but winget is not available on this computer.' + #13#10 + 'Please install ' + Title + ' yourself.', mbInformation, MB_OK);
    Problems := Problems + #13#10 + '- ' + Title + ' still has to be installed.';
    Exit;
  end;
  if MsgBox(Title + ' is needed and was not found.' + #13#10#13#10 + 'Install it now with winget (package ' + Id + ' from ' + Source + ')?', mbConfirmation, MB_YESNO) = IDYES then
  begin
    ProgressPage.SetText('Installing ' + Title + ' with winget...', 'This can take a minute.');
    ProgressPage.Show;
    try
      if not Exec(ExpandConstant('{cmd}'), '/S /C "winget install --id ' + Id + ' -e --accept-source-agreements --accept-package-agreements >> "' + ExpandConstant('{app}\install.log') + '" 2>&1"', '', SW_HIDE, ewWaitUntilTerminated, Code) or (Code <> 0) then
        Problems := Problems + #13#10 + '- ' + Title + ' could not be installed automatically (see install.log).';
    finally
      ProgressPage.Hide;
    end;
  end
  else
    Problems := Problems + #13#10 + '- ' + Title + ' still has to be installed.';
end;

procedure RunStep(const Caption, Detail, CommandLine: String);
var
  Code: Integer;
begin
  ProgressPage.SetText(Caption, Detail);
  ProgressPage.Show;
  try
    if not RunHidden(CommandLine + ' >> "' + ExpandConstant('{app}\install.log') + '" 2>&1', Code) or (Code <> 0) then
      Problems := Problems + #13#10 + '- Step failed: ' + Caption + ' (exit code ' + IntToStr(Code) + ').';
  finally
    ProgressPage.Hide;
  end;
end;

procedure InitializeWizard;
begin
  ProgressPage := CreateOutputMarqueeProgressPage('Setting up LocalDub Studio', 'Please wait; this downloads several gigabytes and can take a while.');
end;

function InitializeSetup: Boolean;
begin
  Result := True;
  if not WebView2Present then
    if not WizardSilent then
      Result := MsgBox('The Microsoft Edge WebView2 runtime was not found. LocalDub Studio will then open in your web browser instead of its own window.' + #13#10#13#10 + 'Windows 11 includes it; for Windows 10 download "WebView2 Runtime" from Microsoft.' + #13#10#13#10 + 'Continue anyway?', mbConfirmation, MB_YESNO) = IDYES;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Uv, Extra, Fetch: String;
begin
  if CurStep <> ssPostInstall then
    Exit;
  Problems := '';
  Uv := '"' + ExpandConstant('{app}\tools\uv.exe') + '"';

  if not FfmpegPresent then
    InstallWithWinget('FFmpeg', 'Gyan.FFmpeg', 'the winget repository');
  if not OllamaPresent then
    InstallWithWinget('Ollama (runs the translation models)', 'Ollama.Ollama', 'the winget repository');

  Extra := '';
  Fetch := '';
  if WizardIsComponentSelected('experimental') then
  begin
    Extra := ' --extra experimental';
    Fetch := Fetch + ' --experimental';
  end;
  if WizardIsComponentSelected('diarization') then
    Fetch := Fetch + ' --diarization';

  RunStep('Installing Python 3.12 and the program libraries...', 'About 2.5 GB (6 GB with the experimental features). Python comes from python-build-standalone, libraries from PyPI.',
    Uv + ' sync --frozen --no-dev' + Extra);

  if WizardIsTaskSelected('models') then
    RunStep('Downloading the speech and voice models...', 'About 3.4 GB from Hugging Face. Optional models are checksum-verified.',
      Uv + ' run --no-sync localdub fetch-models' + Fetch);

  if WizardIsTaskSelected('ollamamodel') and OllamaPresent then
    RunStep('Downloading the translation model {#OllamaModel}...', 'About 3.3 GB from the Ollama registry.',
      '"' + OllamaExe + '" pull {#OllamaModel}');

  if Problems <> '' then
    MsgBox('Setup finished, but some steps need attention:' + #13#10 + Problems + #13#10#13#10 + 'Details: ' + ExpandConstant('{app}\install.log') + #13#10 + 'You can repeat a step later; see docs in the install folder.', mbInformation, MB_OK);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    if DirExists(ExpandConstant('{app}\data')) and (not UninstallSilent) then
      if MsgBox('Delete your LocalDub Studio projects, videos and results as well?' + #13#10#13#10 + ExpandConstant('{app}\data'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(ExpandConstant('{app}\data'), True, True, True);
    if DirExists(ExpandConstant('{app}\models')) and (not UninstallSilent) then
      if MsgBox('Delete the downloaded models (several GB) as well?' + #13#10#13#10 + ExpandConstant('{app}\models'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(ExpandConstant('{app}\models'), True, True, True);
    RemoveDir(ExpandConstant('{app}'));
  end;
end;
