# Buduje i pakuje plugin do ZIP-a gotowego do rejestracji w Designer Studio
# (Plugin packages -> New package).
# Uzycie:  powershell -File webcon-action\package.ps1 [-Sdk 2025|2026]
# -Sdk 2025 buduje wariant dla WEBCON BPS 2025 R2 (paczka z sufiksem -bps2025).

param(
    [ValidateSet("2025", "2026")]
    [string]$Sdk = "2026"
)

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
Write-Host "Wersja pakietu: $version (SDK $Sdk)"

dotnet build (Join-Path $projectDir "WebconPdfSplitterAction.csproj") -c Release -p:Version=$version -p:AssemblyVersion="$version.0" -p:BpsSdk=$Sdk
if ($LASTEXITCODE -ne 0) { throw "Build failed" }

New-Item -ItemType Directory -Force $publishDir | Out-Null
$staging = Join-Path $publishDir "staging"
if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
New-Item -ItemType Directory -Force $staging | Out-Null

# DLL pluginu + zaleznosci NuGet; biblioteki WEBCON SDK dostarcza host BPS
Copy-Item (Join-Path $outDir "WebconPdfSplitterAction.dll") $staging
Copy-Item (Join-Path $outDir "Newtonsoft.Json.dll") $staging
Copy-Item (Join-Path $projectDir "WebconPdfSplitterAction.json") $staging

# nazwa ZIP-a zawiera wersje (i linie SDK dla wariantu 2025), zeby bylo widac,
# ktora paczka jest ktora
$suffix = if ($Sdk -eq "2025") { "-bps2025" } else { "" }
$zipPath = Join-Path $publishDir "WebconPdfSplitterAction-$version$suffix.zip"
if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
# stara paczka bez wersji w nazwie mylila - usun, jesli jeszcze lezy
$legacyZip = Join-Path $publishDir "WebconPdfSplitterAction.zip"
if (Test-Path $legacyZip) { Remove-Item -Force $legacyZip }
Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $zipPath
Remove-Item -Recurse -Force $staging

Write-Host "Pakiet gotowy: $zipPath"
