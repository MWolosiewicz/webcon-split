# Buduje i pakuje plugin do ZIP-a gotowego do rejestracji w Designer Studio
# (Plugin packages -> New package).
# Uzycie:  powershell -File webcon-action\package.ps1

$ErrorActionPreference = "Stop"
$projectDir = $PSScriptRoot
$outDir = Join-Path $projectDir "bin\Release\netstandard2.0"
$publishDir = Join-Path $projectDir "Publish"

# WEBCON cache'uje pluginy po wersji assembly - kazda paczka musi miec nowa wersje,
# inaczej Designer Studio moze dalej uzywac starej kopii DLL.
$versionFile = Join-Path $projectDir "version.txt"
$parts = (Get-Content $versionFile -Raw).Trim().Split(".")
$parts[-1] = [string]([int]$parts[-1] + 1)
$version = $parts -join "."
Set-Content -Path $versionFile -Value $version -Encoding ascii
Write-Host "Wersja pakietu: $version"

dotnet build (Join-Path $projectDir "WebconPdfSplitterAction.csproj") -c Release -p:Version=$version -p:AssemblyVersion="$version.0"
if ($LASTEXITCODE -ne 0) { throw "Build failed" }

New-Item -ItemType Directory -Force $publishDir | Out-Null
$staging = Join-Path $publishDir "staging"
if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
New-Item -ItemType Directory -Force $staging | Out-Null

# DLL pluginu + zaleznosci NuGet; biblioteki WEBCON SDK dostarcza host BPS
Copy-Item (Join-Path $outDir "WebconPdfSplitterAction.dll") $staging
Copy-Item (Join-Path $outDir "Newtonsoft.Json.dll") $staging
Copy-Item (Join-Path $projectDir "WebconPdfSplitterAction.json") $staging

$zipPath = Join-Path $publishDir "WebconPdfSplitterAction.zip"
if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $zipPath
Remove-Item -Recurse -Force $staging

Write-Host "Pakiet gotowy: $zipPath"
