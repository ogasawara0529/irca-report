#Requires -Version 5.0
$InstallDir = "C:\irca-report"
Set-Location $InstallDir

# config.env を環境変数に読み込む
Get-Content "$InstallDir\config.env" | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith('#') -and $line -contains '=') {
        $parts = $line -split '=', 2
        [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim(), 'Process')
    }
}

Write-Host "irca-report サーバー起動中... http://$(hostname):5000/"
python "$InstallDir\server.py"
