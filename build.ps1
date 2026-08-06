$ErrorActionPreference = "Stop"

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if (Test-Path dist) { Remove-Item -Recurse -Force dist }
if (Test-Path build) { Remove-Item -Recurse -Force build }

# M1：从 version.py 读取单一版本来源
$Version = python -c "import version; print(version.APP_VERSION)"

# 动态生成 PyInstaller 版本资源文件（version_info.txt）
$VersionInfo = @"
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=($Version -replace '\.', ',').Split(',') + @(0, 0),
    prodvers=($Version -replace '\.', ',').Split(',') + @(0, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('u', [
        StringStruct('CompanyName', 'ClaudeBeep'),
        StringStruct('FileDescription', 'ClaudeBeep'),
        StringStruct('FileVersion', '$Version'),
        StringStruct('InternalName', 'ClaudeBeep'),
        StringStruct('OriginalFilename', 'ClaudeBeep.exe'),
        StringStruct('ProductName', 'ClaudeBeep'),
        StringStruct('ProductVersion', '$Version')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
"@
Set-Content -Path version_info.txt -Value $VersionInfo -Encoding UTF8

python -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --windowed `
  --name ClaudeBeep `
  --icon assets/icon.ico `
  --manifest ClaudeBeep.manifest `
  --version-file version_info.txt `
  --add-data "static;static" `
  --add-data "assets;assets" `
  --add-data "claudebeep_hook.bat;." `
  --hidden-import websockets `
  --hidden-import lark_oapi `
  --hidden-import lark_oapi.ws `
  --hidden-import dingtalk_stream `
  --hidden-import winotify `
  --hidden-import channels `
  --hidden-import channels.windows_toast `
  --hidden-import channels.weixin `
  --hidden-import channels.qq `
  --hidden-import channels.telegram `
  --hidden-import channels.feishu `
  --hidden-import channels.dingtalk `
  --hidden-import channels.text `
  --hidden-import channels.base `
  --hidden-import config_store `
  --hidden-import notification_core `
  --hidden-import codex_adapter `
  --hidden-import hook_manager `
  --hidden-import tray_menu `
  --hidden-import version `
  --hidden-import common `
  --hidden-import common.log `
  --hidden-import common.paths `
  --hidden-import common.channels_registry `
  --hidden-import common.token_cache `
  --hidden-import listener `
  tray.py

Write-Host "Built dist\ClaudeBeep.exe (version $Version)"
