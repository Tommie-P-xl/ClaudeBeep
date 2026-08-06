$ErrorActionPreference = "Stop"

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if (Test-Path dist) { Remove-Item -Recurse -Force dist }
if (Test-Path build) { Remove-Item -Recurse -Force build }

# M1：从 version.py 读取单一版本来源
$Version = python -c "import version; print(version.APP_VERSION)"
$VersionParts = $Version.Split('.')
# version_info.txt 是 PyInstaller 用 Python eval() 解析的文件，
# 必须写入纯 Python 字面量（不能是 PowerShell 表达式）
$FileVer = "($($VersionParts[0]), $($VersionParts[1]), $($VersionParts[2]), 0)"

# 动态生成 PyInstaller 版本资源文件（version_info.txt）
$VersionInfo = @"
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=$FileVer,
    prodvers=$FileVer,
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
# 内容全 ASCII，用 ascii 编码避免 BOM（PS 5.1 的 UTF8 会写 BOM，可能干扰 PyInstaller 解析）
Set-Content -Path version_info.txt -Value $VersionInfo -Encoding ascii

# 自检：生成的 version_info.txt 必须能被 PyInstaller 的解析器读取，
# 否则直接失败，避免把坏文件送进构建
python -c "from PyInstaller.utils.win32.versioninfo import load_version_info_from_text_file; load_version_info_from_text_file('version_info.txt'); print('version_info.txt OK')"
if ($LASTEXITCODE -ne 0) { Write-Error "version_info.txt 无法被 PyInstaller 解析"; exit 1 }

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

if ($LASTEXITCODE -ne 0) {
  Write-Error "PyInstaller 构建失败，退出码 $LASTEXITCODE"
  exit $LASTEXITCODE
}
Write-Host "Built dist\ClaudeBeep.exe (version $Version)"
