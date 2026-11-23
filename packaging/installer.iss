; Inno Setup 6 script for the PDF Manager install wizard.
;
; Build (packaging\build.ps1 does this after PyInstaller):
;   iscc /DAppVersion=1.2.3 packaging\installer.iss
; Input:  dist\PDF Manager\  (the PyInstaller one-folder build)
; Output: dist\installer\PDF-Manager-Setup-<version>.exe
;
; What the wizard does:
;   * Per-user install, no admin rights (decision F17), into
;     %LOCALAPPDATA%\Programs\PDF Manager, so the app can write its logs folder
;     next to itself (decision C4).
;   * Pages: Welcome -> install location (first install only) -> optional
;     components -> desktop shortcut -> Install -> Finish ("Launch PDF Manager").
;   * Optional components (decisions C11, F31), installed with winget after the
;     app files: Tesseract OCR (unchecked) and LibreOffice (checked only when
;     Microsoft PowerPoint isn't found). A failure never fails the setup.
;   * Checks for the Microsoft Edge WebView2 Runtime and offers the download.
;
; Keep this file ASCII-only: Inno Setup reads BOM-less files as ANSI.

#if VER < EncodeVer(6, 3, 0)
  #error Inno Setup 6.3 or newer is required (for x64compatible).
#endif

#define AppName "PDF Manager"
#define AppExeName "PDF Manager.exe"
; SourcePath is the folder holding this script (packaging\); its parent is the repo root.
#define RepoRoot ExtractFileDir(RemoveBackslashUnlessRoot(SourcePath))
#define BuildDir RepoRoot + "\dist\PDF Manager"

#ifndef AppVersion
  ; Fall back to the version resource PyInstaller embedded in the exe.
  #define AppVersion GetVersionNumbersString(BuildDir + "\" + AppExeName)
#endif
#if AppVersion == ""
  #error Could not determine the version. Pass /DAppVersion=x.y.z or build the app first.
#endif

[Setup]
; Fixed id: lets upgrades and the uninstaller recognise earlier installs. Never change it.
AppId={{6F1C2B9E-4A7D-4E3B-9C55-2D8E0B7A41F3}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppName}
; Per-user install: no UAC prompt for the app itself.
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\{#AppName}
; The location page shows on the first install only; upgrades reuse the old folder.
DisableDirPage=auto
DisableWelcomePage=no
; No Start-menu folder page: the shortcut goes straight into the Start menu.
DisableProgramGroupPage=yes
; No "Ready to install" page: the Next button on the shortcut page reads "Install".
DisableReadyPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
SetupIconFile={#RepoRoot}\PDF Manager.ico
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}
WizardStyle=modern
OutputDir={#RepoRoot}\dist\installer
OutputBaseFilename=PDF-Manager-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
; Close a running PDF Manager (via Restart Manager) before replacing its files.
CloseApplications=yes
RestartApplications=no
; Write a setup log to %TEMP% (Setup Log *.txt) to help diagnose problems.
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
WelcomeLabel2=This will install [name/ver] on your computer.%n%nNo administrator rights are needed: PDF Manager is installed just for you.%n%nClick Next to continue.

[CustomMessages]
ComponentsCaption=Optional helper programs
ComponentsDescription=PDF Manager can install these free programs for you.
ComponentsIntro=You can skip them now and add them later.
OcrCheckbox=Tesseract OCR (text recognition)
OcrExplain=OCR reads the words in scanned pages and pictures, so you can search and copy text in your PDFs.
LibreOfficeCheckbox=LibreOffice (backup for PowerPoint files)
LibreOfficeWithPowerPoint=Microsoft PowerPoint was found on this computer, so PDF Manager will use it. LibreOffice is only a backup in case PowerPoint can't convert a file.
LibreOfficeWithoutPowerPoint=Microsoft PowerPoint wasn't found on this computer. PDF Manager needs PowerPoint or LibreOffice to convert PowerPoint files. LibreOffice is a large download.
AlreadyInstalled=%1 - already installed
ComponentsNote=These programs are installed for everyone on this computer, so Windows may ask for permission. Choose Yes when it does. An internet connection is needed.
StatusInstalling=Installing %1... This can take a few minutes.
StatusPermission=If Windows asks for permission, choose Yes.
StatusChecking=Checking for the Windows Package Manager (winget)...
OcrName=Tesseract OCR
LibreOfficeName=LibreOffice
NotInstalledHeader=PDF Manager is installed, but setup couldn't install these optional programs:
NoWinget=(The Windows Package Manager, winget, isn't available on this computer.)
OcrLater=Tesseract OCR: you can install it later in PDF Manager under Settings.
LibreOfficeLater=LibreOffice: you can download it later from libreoffice.org.
LibreOfficeNeeded=Until PowerPoint or LibreOffice is installed, PowerPoint files can't be converted. PDF files work normally.
WebView2Missing=PDF Manager needs the Microsoft Edge WebView2 Runtime, a free Windows component from Microsoft. It normally comes with Windows 11, but it wasn't found on this computer.
WebView2Continue=Setup will continue either way. Do you want to download it now? Run the downloaded file to install it.
WebView2StillMissing=The Microsoft Edge WebView2 Runtime still isn't installed, so PDF Manager won't open yet.
WebView2DownloadNow=Do you want to download it now? Run the downloaded file to install it, then open PDF Manager from the Start menu.
RemoveSettings=Do you also want to remove your PDF Manager settings?
RemoveSettingsHint=Choose No to keep them for the next time you install PDF Manager.

[Tasks]
; Checked by default: the easiest way back into the app for most people.
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; Remove the old bundle on upgrade so stale libraries from an earlier version
; can't be loaded. The folder is fully replaced by [Files] below.
Type: filesandordirs; Name: "{app}\_internal"
; Same for the licence files, so an upgrade doesn't leave notices for components
; the new version no longer ships.
Type: filesandordirs; Name: "{app}\licenses"

[Files]
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Licences next to the app (see LICENSING.md): the original code's MIT licence, the AGPL-3.0
; that the distributed app is under (it includes PyMuPDF), the licensing summary, the
; third-party notices and every bundled component's licence text.
Source: "{#RepoRoot}\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "{#RepoRoot}\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#RepoRoot}\LICENSE-AGPL-3.0.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#RepoRoot}\LICENSING.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#RepoRoot}\licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
; Hidden while WebView2 is missing: the app can't open without it.
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent; Check: IsWebView2Installed

[UninstallDelete]
; The logs folder is created by the app, so the uninstaller doesn't know about it.
; It only holds diagnostics, so it goes with the app.
Type: filesandordirs; Name: "{app}\logs"

[Code]
const
  { Registry key of the Evergreen WebView2 Runtime, see
    https://learn.microsoft.com/microsoft-edge/webview2/concepts/distribution }
  WebView2ClientKey = 'Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  { Microsoft's official Evergreen Bootstrapper download. }
  WebView2DownloadUrl = 'https://go.microsoft.com/fwlink/p/?LinkId=2124703';
  OcrPackageId = 'UB-Mannheim.TesseractOCR';
  LibreOfficePackageId = 'TheDocumentFoundation.LibreOffice';
  { winget exit codes that mean "nothing to do, it is already there".
    0x8A15002B: no newer version available. 0x8A150061: package already installed. }
  WingetNoApplicableUpdate = -1978335189;
  WingetPackageAlreadyInstalled = -1978335135;

var
  ComponentsPage: TWizardPage;
  OcrCheckBox: TNewCheckBox;
  LibreOfficeCheckBox: TNewCheckBox;
  PowerPointFound: Boolean;
  OcrAlreadyInstalled: Boolean;
  LibreOfficeAlreadyInstalled: Boolean;

{ ---------- Detection ---------- }

{ True if a WebView2 "pv" (version) value exists and is a real version. }
function WebView2VersionAt(const RootKey: Integer; const SubKey: String): Boolean;
var
  Version: String;
begin
  Result := RegQueryStringValue(RootKey, SubKey, 'pv', Version) and
            (Version <> '') and (Version <> '0.0.0.0');
end;

{ Whether the Microsoft Edge WebView2 Runtime is installed, machine-wide or for this user.
  Also used as the Check for the "Launch PDF Manager" box. }
function IsWebView2Installed: Boolean;
begin
  { Machine-wide installs register under the 32-bit view (WOW6432Node) on 64-bit Windows. }
  Result := WebView2VersionAt(HKLM32, 'SOFTWARE\' + WebView2ClientKey);
  if not Result and IsWin64 then
    Result := WebView2VersionAt(HKLM64, 'SOFTWARE\' + WebView2ClientKey);
  if not Result then
    Result := WebView2VersionAt(HKCU, 'Software\' + WebView2ClientKey);
end;

{ Whether Microsoft PowerPoint can be automated: the same registry key the app's
  converter checks (converter.tools.locate.powerpoint_installed), in both registry views. }
function IsPowerPointInstalled: Boolean;
begin
  Result := RegKeyExists(HKCR32, 'PowerPoint.Application\CLSID');
  if not Result and IsWin64 then
    Result := RegKeyExists(HKCR64, 'PowerPoint.Application\CLSID');
end;

{ Whether Tesseract is already installed in one of its usual places. }
function IsTesseractInstalled: Boolean;
var
  InstallDir: String;
begin
  Result := FileExists(ExpandConstant('{commonpf32}\Tesseract-OCR\tesseract.exe')) or
            FileExists(ExpandConstant('{localappdata}\Programs\Tesseract-OCR\tesseract.exe'));
  if not Result and IsWin64 then
    Result := FileExists(ExpandConstant('{commonpf64}\Tesseract-OCR\tesseract.exe'));
  if not Result and RegQueryStringValue(HKLM, 'SOFTWARE\Tesseract-OCR', 'InstallDir', InstallDir) then
    Result := FileExists(AddBackslash(RemoveQuotes(InstallDir)) + 'tesseract.exe');
end;

{ Whether LibreOffice is already installed in one of its usual places. }
function IsLibreOfficeInstalled: Boolean;
begin
  Result := FileExists(ExpandConstant('{commonpf32}\LibreOffice\program\soffice.exe')) or
            FileExists(ExpandConstant('{localappdata}\Programs\LibreOffice\program\soffice.exe'));
  if not Result and IsWin64 then
    Result := FileExists(ExpandConstant('{commonpf64}\LibreOffice\program\soffice.exe'));
end;

procedure OpenWebView2Download;
var
  ErrorCode: Integer;
begin
  ShellExec('open', WebView2DownloadUrl, '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode);
end;

{ ---------- Optional components page ---------- }

{ Adds a word-wrapped label to the components page and returns its bottom edge. }
function AddText(const Caption: String; const Left, Top: Integer): Integer;
var
  Lbl: TNewStaticText;
begin
  Lbl := TNewStaticText.Create(ComponentsPage);
  Lbl.Parent := ComponentsPage.Surface;
  Lbl.Left := Left;
  Lbl.Top := Top;
  { Width first, then WordWrap + AutoSize: the label then grows downwards only. }
  Lbl.Width := ComponentsPage.SurfaceWidth - Left;
  Lbl.WordWrap := True;
  Lbl.AutoSize := True;
  Lbl.Caption := Caption;
  Result := Lbl.Top + Lbl.Height;
end;

{ Adds a checkbox to the components page. }
function AddCheckBox(const Caption: String; const Top: Integer; const Checked, Enabled: Boolean): TNewCheckBox;
begin
  Result := TNewCheckBox.Create(ComponentsPage);
  Result.Parent := ComponentsPage.Surface;
  Result.Left := 0;
  Result.Top := Top;
  Result.Width := ComponentsPage.SurfaceWidth;
  Result.Height := ScaleY(17);
  Result.Caption := Caption;
  Result.Checked := Checked;
  Result.Enabled := Enabled;
end;

procedure CreateComponentsPage;
var
  Y: Integer;
  Caption, Explanation: String;
  Indent: Integer;
begin
  ComponentsPage := CreateCustomPage(wpSelectDir,
    CustomMessage('ComponentsCaption'), CustomMessage('ComponentsDescription'));
  Indent := ScaleX(18);

  Y := AddText(CustomMessage('ComponentsIntro'), 0, 0) + ScaleY(14);

  { Tesseract OCR: always unchecked by default (decision F31). }
  Caption := CustomMessage('OcrCheckbox');
  if OcrAlreadyInstalled then
    Caption := FmtMessage(CustomMessage('AlreadyInstalled'), [Caption]);
  OcrCheckBox := AddCheckBox(Caption, Y, False, not OcrAlreadyInstalled);
  Y := AddText(CustomMessage('OcrExplain'), Indent, OcrCheckBox.Top + OcrCheckBox.Height + ScaleY(2)) + ScaleY(14);

  { LibreOffice: checked only when PowerPoint isn't found (decisions C11, F31). }
  Caption := CustomMessage('LibreOfficeCheckbox');
  if LibreOfficeAlreadyInstalled then
    Caption := FmtMessage(CustomMessage('AlreadyInstalled'), [Caption]);
  LibreOfficeCheckBox := AddCheckBox(Caption, Y,
    not PowerPointFound and not LibreOfficeAlreadyInstalled, not LibreOfficeAlreadyInstalled);
  if PowerPointFound then
    Explanation := CustomMessage('LibreOfficeWithPowerPoint')
  else
    Explanation := CustomMessage('LibreOfficeWithoutPowerPoint');
  Y := AddText(Explanation, Indent, LibreOfficeCheckBox.Top + LibreOfficeCheckBox.Height + ScaleY(2)) + ScaleY(18);

  AddText(CustomMessage('ComponentsNote'), 0, Y);
end;

{ ---------- Installing the components with winget ---------- }

function IsWingetAvailable: Boolean;
var
  ResultCode: Integer;
begin
  { Run through cmd.exe so winget's App Execution Alias is found on PATH. }
  Result := Exec(ExpandConstant('{cmd}'), '/C winget --version', '', SW_HIDE,
                 ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
  Log(Format('winget available: %d (exit code %d)', [Ord(Result), ResultCode]));
end;

{ Installs one winget package, showing status text. Returns True on success,
  including when the package turns out to be installed already. }
function InstallWithWinget(const PackageId, DisplayName: String): Boolean;
var
  Params: String;
  ResultCode: Integer;
begin
  WizardForm.StatusLabel.Caption := FmtMessage(CustomMessage('StatusInstalling'), [DisplayName]);
  WizardForm.FilenameLabel.Caption := CustomMessage('StatusPermission');
  { --source winget: both packages live in the community repository, and this
    avoids prompts from the Microsoft Store source. }
  Params := '/C winget install --id ' + PackageId + ' -e --source winget' +
            ' --accept-source-agreements --accept-package-agreements';
  Log('Running: cmd.exe ' + Params);
  if not Exec(ExpandConstant('{cmd}'), Params, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    Log('Could not start winget: ' + SysErrorMessage(ResultCode));
    Result := False;
    Exit;
  end;
  Log(Format('winget exit code for %s: %d', [PackageId, ResultCode]));
  Result := (ResultCode = 0) or (ResultCode = WingetNoApplicableUpdate) or
            (ResultCode = WingetPackageAlreadyInstalled);
end;

procedure InstallOptionalComponents;
var
  WantOcr, WantLibreOffice, OcrFailed, LibreOfficeFailed, NoWinget: Boolean;
  Summary: String;
begin
  { /NOOPTIONAL=1 on the command line skips the optional programs entirely
    (automated tests and administrators installing them separately). }
  if ExpandConstant('{param:NOOPTIONAL|0}') = '1' then
  begin
    Log('Optional components skipped (/NOOPTIONAL=1).');
    Exit;
  end;
  WantOcr := OcrCheckBox.Checked and OcrCheckBox.Enabled;
  WantLibreOffice := LibreOfficeCheckBox.Checked and LibreOfficeCheckBox.Enabled;
  if not WantOcr and not WantLibreOffice then
    Exit;

  { These installs report no progress, so show a moving bar instead. }
  WizardForm.ProgressGauge.Style := npbstMarquee;
  try
    WizardForm.StatusLabel.Caption := CustomMessage('StatusChecking');
    WizardForm.FilenameLabel.Caption := '';
    NoWinget := not IsWingetAvailable;
    { Plain ifs rather than "and"/"or" chains, so an install never runs as a side
      effect of evaluating a condition. }
    OcrFailed := False;
    if WantOcr then
    begin
      if NoWinget then
        OcrFailed := True
      else
        OcrFailed := not InstallWithWinget(OcrPackageId, CustomMessage('OcrName'));
    end;
    LibreOfficeFailed := False;
    if WantLibreOffice then
    begin
      if NoWinget then
        LibreOfficeFailed := True
      else
        LibreOfficeFailed := not InstallWithWinget(LibreOfficePackageId, CustomMessage('LibreOfficeName'));
    end;
  finally
    WizardForm.ProgressGauge.Style := npbstNormal;
    WizardForm.FilenameLabel.Caption := '';
  end;

  if not OcrFailed and not LibreOfficeFailed then
    Exit;

  Summary := CustomMessage('NotInstalledHeader') + #13#10;
  if NoWinget then
    Summary := Summary + CustomMessage('NoWinget') + #13#10;
  if OcrFailed then
    Summary := Summary + #13#10 + '- ' + CustomMessage('OcrLater');
  if LibreOfficeFailed then
  begin
    Summary := Summary + #13#10 + '- ' + CustomMessage('LibreOfficeLater');
    if not PowerPointFound then
      Summary := Summary + #13#10#13#10 + CustomMessage('LibreOfficeNeeded');
  end;
  SuppressibleMsgBox(Summary, mbInformation, MB_OK, IDOK);
end;

{ ---------- Event functions ---------- }

function InitializeSetup: Boolean;
begin
  Result := True;
  if not IsWebView2Installed then
  begin
    Log('WebView2 Runtime not found.');
    if SuppressibleMsgBox(CustomMessage('WebView2Missing') + #13#10#13#10 +
                          CustomMessage('WebView2Continue'), mbConfirmation, MB_YESNO, IDNO) = IDYES then
      OpenWebView2Download;
  end;
end;

procedure InitializeWizard;
begin
  PowerPointFound := IsPowerPointInstalled;
  OcrAlreadyInstalled := IsTesseractInstalled;
  LibreOfficeAlreadyInstalled := IsLibreOfficeInstalled;
  { Keep the argument list on the same line: in [Code], a line starting with "["
    is read by Inno Setup as a new section tag. }
  Log(Format('PowerPoint found: %d, Tesseract found: %d, LibreOffice found: %d', [
    Ord(PowerPointFound), Ord(OcrAlreadyInstalled), Ord(LibreOfficeAlreadyInstalled)]));
  CreateComponentsPage;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    { The app files are in place; now the optional programs. }
    InstallOptionalComponents;
    if not IsWebView2Installed then
      if SuppressibleMsgBox(CustomMessage('WebView2StillMissing') + #13#10#13#10 +
                            CustomMessage('WebView2DownloadNow'), mbError, MB_YESNO, IDNO) = IDYES then
        OpenWebView2Download;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  SettingsDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    { Settings live outside the app folder. Ask before removing them, default No,
      so a reinstall keeps them. A silent uninstall always keeps them. }
    SettingsDir := ExpandConstant('{localappdata}\PDFManager');
    if DirExists(SettingsDir) and not UninstallSilent then
      if MsgBox(CustomMessage('RemoveSettings') + #13#10#13#10 + CustomMessage('RemoveSettingsHint'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(SettingsDir, True, True, True);
  end;
end;
