#Requires -Version 5.0
$InstallDir = "C:\irca-report"
Set-Location $InstallDir

Write-Host "$(Get-Date -Format 'yyyy/MM/dd HH:mm:ss') collect.py 開始"

python "$InstallDir\collect.py"

if ($LASTEXITCODE -eq 0) {
    Write-Host "$(Get-Date -Format 'yyyy/MM/dd HH:mm:ss') 完了"
} else {
    Write-Error "collect.py が失敗しました（終了コード: $LASTEXITCODE）"
    exit 1
}
