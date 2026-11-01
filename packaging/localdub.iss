; LocalDub Studio installer (Inno Setup 6). Build with: uv run python packaging/build_release.py
; The icon file has a new name on purpose: Windows caches icons by path, so a changed picture under
; the old name would keep showing the old one on shortcuts.
; The build script copies tools\uv.exe next to this file and passes /DAppVersion=x.y.z.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "LocalDub Studio"
#define AppExe "{app}\.venv\Scripts\localdub-app.exe"
#define OllamaModel "translategemma:4b"
#define UserData "{localappdata}\LocalDub Studio"

[Setup]
AppId={{6E0B8F6E-3B1D-4C52-9E0A-7C6F0B7D4A11}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=LocalDub Studio
AppMutex=LocalDubStudioRunning
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Installs into Program Files. Running elevated also makes the Python junction that uv creates trusted,
; which Windows' RedirectionGuard requires (a user-created junction fails with error 448).
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\release
OutputBaseFilename=LocalDub-Studio-{#AppVersion}-Setup
SetupIconFile=..\localdub\assets\localdub-orange.ico
UninstallDisplayIcon={app}\localdub\assets\localdub-orange.ico
UninstallDisplayName={#AppName}
InfoBeforeFile=setup-info.txt
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
CloseApplications=no
DiskSpanning=no
; Makes Windows refresh its icon cache when the shortcuts change.
ChangesAssociations=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\localdub\*"; DestDir: "{app}\localdub"; Excludes: "__pycache__,*.pyc"; Flags: recursesubdirs ignoreversion
Source: "..\frontend\dist\*"; DestDir: "{app}\frontend\dist"; Flags: recursesubdirs ignoreversion
Source: "..\pyproject.toml"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\uv.lock"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\.python-version"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\docs\LICENSES.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\docs\QUALITY.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "tools\uv.exe"; DestDir: "{app}\tools"; Flags: ignoreversion
Source: "installed.marker"; DestDir: "{app}"; DestName: ".installed"; Flags: ignoreversion
Source: "THIRD-PARTY-uv.txt"; DestDir: "{app}\tools"; Flags: ignoreversion
Source: "precompile.py"; DestDir: "{app}\tools"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{#AppExe}"; WorkingDir: "{app}"; IconFilename: "{app}\localdub\assets\localdub-orange.ico"
Name: "{autodesktop}\{#AppName}"; Filename: "{#AppExe}"; WorkingDir: "{app}"; IconFilename: "{app}\localdub\assets\localdub-orange.ico"; Tasks: desktopicon

[Run]
Filename: "{#AppExe}"; WorkingDir: "{app}"; Description: "Start {#AppName}"; Flags: nowait postinstall skipifsilent runasoriginaluser; Check: AppInstalled

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\localdub"
Type: filesandordirs; Name: "{app}\frontend"
Type: filesandordirs; Name: "{app}\tools"
Type: files; Name: "{app}\install.log"
Type: files; Name: "{app}\.installed"

[Code]
var
  ProgressPage: TOutputMarqueeProgressWizardPage;
  ModePage: TInputOptionWizardPage;
  Problems: String;
  OldVersion, OldUninstaller: String;

const
  UninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{6E0B8F6E-3B1D-4C52-9E0A-7C6F0B7D4A11}_is1';

procedure FindOldInstall;
var
  Raw: String;
begin
  OldVersion := '';
  OldUninstaller := '';
  if RegQueryStringValue(HKLM, UninstallKey, 'UninstallString', Raw) then
  begin
    OldUninstaller := RemoveQuotes(Raw);
    if not RegQueryStringValue(HKLM, UninstallKey, 'DisplayVersion', OldVersion) then
      OldVersion := '?';
  end;
end;

{ update (default) | repair | fresh. Silent setups choose with /MODE=repair or /MODE=fresh. }
function InstallMode: String;
begin
  Result := LowerCase(ExpandConstant('{param:MODE|}'));
  if (Result <> 'repair') and (Result <> 'fresh') then
  begin
    Result := 'update';
    if (OldVersion <> '') and (not WizardSilent) then
    begin
      if ModePage.SelectedValueIndex = 1 then
        Result := 'repair'
      else if ModePage.SelectedValueIndex = 2 then
        Result := 'fresh';
    end;
  end;
end;

function WebView2Present: Boolean;
var
  Version: String;
begin
  Result :=
    (RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0')) or
    (RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0'));
end;

function UserLog: String;
begin
  { Program Files is read-only for the original (non-elevated) user, so its commands log here. }
  ForceDirectories(ExpandConstant('{#UserData}'));
  Result := ExpandConstant('{#UserData}\install-user.log');
end;

function AppInstalled: Boolean;
begin
  Result := FileExists(ExpandConstant('{#AppExe}'));
end;

function LastLogLines(const Count: Integer): String;
var
  Lines: TArrayOfString;
  I, First: Integer;
begin
  Result := '';
  if LoadStringsFromFile(ExpandConstant('{app}\install.log'), Lines) then
  begin
    First := GetArrayLength(Lines) - Count;
    if First < 0 then
      First := 0;
    for I := First to GetArrayLength(Lines) - 1 do
      Result := Result + Lines[I] + #13#10;
  end;
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

procedure ShowProgress(const Caption, Detail: String);
begin
  { The progress page is only for the interactive wizard; silent setups never touch it. }
  if not WizardSilent then
  begin
    ProgressPage.SetText(Caption, Detail);
    ProgressPage.Show;
  end;
end;

procedure HideProgress;
begin
  if not WizardSilent then
    ProgressPage.Hide;
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
    ShowProgress('Installing ' + Title + ' with winget...', 'This can take a minute.');
    try
      { winget and per-user programs (FFmpeg, Ollama) must be installed as the user, not as the elevated admin. }
      if not ExecAsOriginalUser(ExpandConstant('{cmd}'), '/S /C "winget install --id ' + Id + ' -e --accept-source-agreements --accept-package-agreements >> "' + UserLog + '" 2>&1"', '', SW_HIDE, ewWaitUntilTerminated, Code) or (Code <> 0) then
        Problems := Problems + #13#10 + '- ' + Title + ' could not be installed automatically (see install.log).';
    finally
      HideProgress;
    end;
  end
  else
    Problems := Problems + #13#10 + '- ' + Title + ' still has to be installed.';
end;

function RunLogged(const CommandLine: String; AsOriginalUser: Boolean; var Code: Integer): Boolean;
var
  Full: String;
begin
  if AsOriginalUser then
    Full := '/S /C "' + CommandLine + ' >> "' + UserLog + '" 2>&1"'
  else
    Full := '/S /C "' + CommandLine + ' >> "' + ExpandConstant('{app}\install.log') + '" 2>&1"';
  if AsOriginalUser then
    Result := ExecAsOriginalUser(ExpandConstant('{cmd}'), Full, ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, Code)
  else
    Result := Exec(ExpandConstant('{cmd}'), Full, ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, Code);
end;

procedure RunStep(const Caption, Detail, CommandLine: String; AsOriginalUser: Boolean);
var
  Code: Integer;
begin
  Log('Step: ' + Caption);
  ShowProgress(Caption, Detail);
  try
    if not RunLogged(CommandLine, AsOriginalUser, Code) or (Code <> 0) then
      Problems := Problems + #13#10 + '- Step failed: ' + Caption + ' (exit code ' + IntToStr(Code) + '). Last lines of install.log:' + #13#10 + LastLogLines(6);
  finally
    HideProgress;
  end;
  Log('Step finished: ' + Caption);
end;

procedure InitializeWizard;
begin
  ProgressPage := CreateOutputMarqueeProgressPage('Setting up LocalDub Studio', 'Please wait; this downloads several gigabytes and can take a while.');
  ModePage := CreateInputOptionPage(wpWelcome, 'LocalDub Studio is already installed',
    'Installed version: ' + OldVersion + '. This setup installs {#AppVersion}. What should it do?', '', True, False);
  ModePage.Add('Update to {#AppVersion}. Keeps your projects, downloaded models and settings. (recommended)');
  ModePage.Add('Repair: reinstall the program files and its libraries from scratch, for when something is broken. Keeps your projects and models.');
  ModePage.Add('Remove the old version first, then install {#AppVersion}. Keeps your projects and models (delete them from Windows Settings > Apps if you want that).');
  ModePage.SelectedValueIndex := 0;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if (ModePage <> nil) and (PageID = ModePage.ID) then
    Result := WizardSilent or (OldVersion = '');
end;

function InitializeSetup: Boolean;
begin
  Result := True;
  FindOldInstall;
  if not WebView2Present then
    if not WizardSilent then
      Result := MsgBox('The Microsoft Edge WebView2 runtime was not found. LocalDub Studio will then open in your web browser instead of its own window.' + #13#10#13#10 + 'Windows 11 includes it; for Windows 10 download "WebView2 Runtime" from Microsoft.' + #13#10#13#10 + 'Continue anyway?', mbConfirmation, MB_YESNO) = IDYES;
end;

{ Runs before Setup writes anything (also for silent setups). The old version has to be removed here:
  Setup creates its uninstall files as soon as it starts installing. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode, I: Integer;
begin
  Result := '';
  if OldVersion = '' then
    Exit;
  begin
    Log('Existing installation ' + OldVersion + ', mode: ' + InstallMode);
    { files that a newer version no longer ships must not linger (old modules, old web assets) }
    DelTree(ExpandConstant('{app}\localdub'), True, True, True);
    DelTree(ExpandConstant('{app}\frontend'), True, True, True);
    if (InstallMode = 'fresh') and FileExists(OldUninstaller) then
    begin
      { Silent: the old uninstaller keeps projects, models and settings and asks nothing. }
      ShowProgress('Removing the old version...', 'Your projects and models are kept.');
      try
        Exec(OldUninstaller, '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
        Log('Old uninstaller finished with code ' + IntToStr(ResultCode));
        { The uninstaller finishes by a helper process that deletes its own files a moment later. Wait for
          that, or it could delete the uninstaller of the version being installed now. }
        for I := 1 to 120 do
        begin
          if not FileExists(OldUninstaller) then
            Break;
          Sleep(500);
        end;
        Log('Old uninstaller gone: ' + IntToStr(Ord(not FileExists(OldUninstaller))));
      finally
        HideProgress;
      end;
    end
    else if InstallMode = 'repair' then
    begin
      DelTree(ExpandConstant('{app}\.venv'), True, True, True);
      DelTree(ExpandConstant('{app}\python'), True, True, True);
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Uv, EnvPrefix: String;
begin
  if CurStep = ssDone then
    Log('Setup is done');
  if CurStep <> ssPostInstall then
    Exit;
  Log('Post-install started');
  Problems := '';
  Uv := '"' + ExpandConstant('{app}\tools\uv.exe') + '"';

  if not FfmpegPresent then
    InstallWithWinget('FFmpeg', 'Gyan.FFmpeg', 'the winget repository');
  if not OllamaPresent then
    InstallWithWinget('Ollama (runs the translation models)', 'Ollama.Ollama', 'the winget repository');


  { Always use uv's own Python (never whatever is on this PC), kept inside the install folder rather than
    in one user's profile. The AI models are downloaded later inside the app, as the user, with visible
    progress (an elevated installer would leave them unreadable for the normal user). }
  EnvPrefix := 'set "UV_PYTHON_PREFERENCE=only-managed" && set "UV_PYTHON_INSTALL_DIR=' + ExpandConstant('{app}\python') + '" && ';

  RunStep('Installing Python 3.12 and the program libraries...', 'About 2.5 GB. Python comes from python-build-standalone, libraries from PyPI.',
    EnvPrefix + Uv + ' sync --frozen --no-dev', False);
  if not AppInstalled then
  begin
    { A leftover or damaged .venv from an earlier attempt: start again from a clean one. }
    Log('The program is missing after the first attempt; retrying with a clean environment');
    DelTree(ExpandConstant('{app}\.venv'), True, True, True);
    DelTree(ExpandConstant('{app}\python'), True, True, True);
    RunStep('Installing Python 3.12 and the program libraries (second attempt)...', 'Starting from a clean environment.',
      EnvPrefix + Uv + ' sync --frozen --no-dev', False);
  end;

  if not AppInstalled then
    Problems := Problems + #13#10 + '- LocalDub Studio could not be set up: the program files are missing. See install.log.'
  else
    { Program Files is read-only for the user who runs the program, so Python could never save its compiled
      files and would compile every library again on every start (about 5 seconds slower). }
    RunStep('Preparing the program for a fast start...', 'Compiling the program files once.',
      '"' + ExpandConstant('{app}\.venv\Scripts\python.exe') + '" "' + ExpandConstant('{app}\tools\precompile.py') + '"', False);
  Log('Post-install finished; problems: [' + Problems + ']');
  if (Problems <> '') and (not WizardSilent) then
    MsgBox('Setup finished, but some steps need attention:' + #13#10 + Problems + #13#10#13#10 + 'Details: ' + ExpandConstant('{app}\install.log') + #13#10 + 'You can repeat a step later; see docs in the install folder.', mbInformation, MB_OK);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Data, Models, Extras: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    Data := ExpandConstant('{#UserData}\data');
    Models := ExpandConstant('{#UserData}\models');
    Extras := ExpandConstant('{#UserData}\extras');
    if DirExists(Data) and (not UninstallSilent) then
      if MsgBox('Delete your LocalDub Studio projects, videos and results as well?' + #13#10#13#10 + Data, mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(Data, True, True, True);
    if DirExists(Models) and (not UninstallSilent) then
      if MsgBox('Delete the downloaded models (several GB) as well?' + #13#10#13#10 + Models, mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(Models, True, True, True);
    { The optional PyTorch packages the app installed itself (several GB) go with the models. }
    if DirExists(Extras) and (not UninstallSilent) then
      if MsgBox('Delete the optional packages (PyTorch, several GB) as well?' + #13#10#13#10 + Extras, mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(Extras, True, True, True);
    { small programs the app installed for the YouTube import (yt-dlp, Deno): no question needed }
    DelTree(ExpandConstant('{#UserData}\youtube-tools'), True, True, True);
    { leftovers of an interrupted package installation }
    DelTree(ExpandConstant('{#UserData}\extras-download'), True, True, True);
    DelTree(ExpandConstant('{#UserData}\extras-new'), True, True, True);
    RemoveDir(ExpandConstant('{#UserData}'));
    RemoveDir(ExpandConstant('{app}'));
  end;
end;
