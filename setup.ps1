#Requires -RunAsAdministrator
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$InstallDir = "C:\irca-report"

Write-Host "=== irca-report セットアップ ===" -ForegroundColor Cyan

# ディレクトリ作成
New-Item -ItemType Directory -Force -Path $InstallDir        | Out-Null
New-Item -ItemType Directory -Force -Path "$InstallDir\data" | Out-Null
Write-Host "ディレクトリ作成完了: $InstallDir"

# Python 依存関係
Write-Host "Python 依存関係インストール中..."
python -m pip install -r "$InstallDir\requirements.txt"

# IIS インストール
Write-Host "IIS インストール中..."
Install-WindowsFeature -Name Web-Server, Web-Mgmt-Console -IncludeManagementTools | Out-Null
Import-Module WebAdministration

# デフォルトサイトを停止（ポート 80 競合対策）
Stop-Website -Name "Default Web Site" -ErrorAction SilentlyContinue

# IIS サイト作成
$siteName = "irca-report"
if (Get-Website -Name $siteName -ErrorAction SilentlyContinue) {
    Remove-Website -Name $siteName
}
New-Website -Name $siteName -Port 80 -PhysicalPath "$InstallDir\web" | Out-Null
Write-Host "IIS サイト作成完了"

# /data/ 仮想ディレクトリ（report.json を配信）
New-WebVirtualDirectory -Site $siteName -Name "data" -PhysicalPath "$InstallDir\data" | Out-Null
Write-Host "/data/ 仮想ディレクトリ設定完了"

# data ディレクトリの web.config（キャッシュ無効・JSON MIME）
@'
<?xml version="1.0" encoding="UTF-8"?>
<configuration>
  <system.webServer>
    <staticContent>
      <remove fileExtension=".json" />
      <mimeMap fileExtension=".json" mimeType="application/json" />
    </staticContent>
    <httpProtocol>
      <customHeaders>
        <add name="Cache-Control" value="no-store, no-cache" />
        <add name="Pragma" value="no-cache" />
      </customHeaders>
    </httpProtocol>
  </system.webServer>
</configuration>
'@ | Out-File -FilePath "$InstallDir\data\web.config" -Encoding UTF8

# IIS_IUSRS に data ディレクトリの読み取り権限を付与
$acl  = Get-Acl "$InstallDir\data"
$rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
    "IIS_IUSRS", "ReadAndExecute", "ContainerInherit,ObjectInherit", "None", "Allow"
)
$acl.AddAccessRule($rule)
Set-Acl "$InstallDir\data" $acl
Write-Host "IIS パーミッション設定完了"

# Windows ファイアウォール（ポート 80 開放）
New-NetFirewallRule `
    -DisplayName "irca-report HTTP" `
    -Direction Inbound -Protocol TCP -LocalPort 80 `
    -Action Allow -ErrorAction SilentlyContinue | Out-Null
Write-Host "ファイアウォール ポート 80 開放完了"

# タスクスケジューラ（毎週月曜 06:00）
$taskName = "irca-report-collect"
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

$action    = New-ScheduledTaskAction `
                 -Execute "powershell.exe" `
                 -Argument "-NonInteractive -ExecutionPolicy Bypass -File `"$InstallDir\run.ps1`""
$trigger   = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At "06:00"
$settings  = New-ScheduledTaskSettingsSet `
                 -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
                 -StartWhenAvailable $true
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest

Register-ScheduledTask `
    -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null
Write-Host "タスクスケジューラ設定完了（毎週月曜 06:00）"

Write-Host ""
Write-Host "=== セットアップ完了 ===" -ForegroundColor Green
Write-Host "動作確認 : powershell -File C:\irca-report\run.ps1" -ForegroundColor Yellow
Write-Host "ダッシュボード: http://210.140.116.60/"             -ForegroundColor Yellow
