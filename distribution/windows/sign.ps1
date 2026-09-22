param([Parameter(Mandatory=$true)][string]$File)
$ErrorActionPreference = 'Stop'
$tool = (Get-ChildItem 'C:\Program Files (x86)\Windows Kits\10\bin\*\x64\signtool.exe' | Sort-Object FullName -Descending | Select-Object -First 1).FullName
if (-not $tool) { throw 'Windows SDK signtool is required.' }
if (-not $env:WINDOWS_CERTIFICATE_FILE -or -not $env:WINDOWS_CERTIFICATE_PASSWORD) { throw 'Release signing certificate is not configured.' }
& $tool sign /fd SHA256 /td SHA256 /tr http://timestamp.digicert.com /f $env:WINDOWS_CERTIFICATE_FILE /p $env:WINDOWS_CERTIFICATE_PASSWORD $File
if ($LASTEXITCODE -ne 0) { throw "Signing failed: $File" }
& $tool verify /pa $File
if ($LASTEXITCODE -ne 0) { throw "Signature verification failed: $File" }
