$ErrorActionPreference = "Stop"

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if (Test-Path dist) { Remove-Item -Recurse -Force dist }
if (Test-Path build) { Remove-Item -Recurse -Force build }

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
  tray.py

Write-Host "Built dist\ClaudeBeep.exe"
