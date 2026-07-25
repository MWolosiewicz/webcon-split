# Buduje i pakuje plugin do ZIP-a gotowego do rejestracji w Designer Studio
# (Plugin packages -> New package).
# Uzycie:  powershell -File webcon-action\package.ps1 [-Sdk 2025|2026|both]
# Nazwa ZIP-a: WebconPdfSplitterAction-<linia BPS>-<wersja>.zip,
# np. WebconPdfSplitterAction-2025r2-1.0.12.19.zip
#
# Domyslnie buduje OBIE linie BPS z JEDNEGO numeru wersji. Wczesniej wersja
# byla podbijana przy kazdym uruchomieniu, wiec ten sam kod wychodzil jako
# 2026r1-1.0.12.17 i 2025r2-1.0.12.18 - z nazw nie dalo sie odczytac, ze to
# para. Rozroznienie niesie teraz wylacznie etykieta linii BPS.

param(
    [ValidateSet("2025", "2026", "both")]
    [string]$Sdk = "both"
)

$ErrorActionPreference = "Stop"

# etykieta linii BPS w nazwie paczki; musi odpowiadac linii pakietu SDK
# wybieranego w csproj przez -p:BpsSdk (2025 -> 25.2.x = R2, 2026 -> 26.1.x = R1)
$bpsLabels = @{ "2025" = "2025r2"; "2026" = "2026r1" }
$lines = if ($Sdk -eq "both") { @("2025", "2026") } else { @($Sdk) }
$projectDir = $PSScriptRoot
$publishDir = Join-Path $projectDir "Publish"

# WEBCON cache'uje pluginy po wersji assembly - kazda paczka musi miec nowa wersje,
# inaczej Designer Studio moze dalej uzywac starej kopii DLL. Podbijamy RAZ,
# przed petla po liniach BPS.
$versionFile = Join-Path $projectDir "version.txt"
$parts = (Get-Content $versionFile -Raw).Trim().Split(".")
# wersja jest 4-czesciowa (= wersja assembly); starszy 3-czesciowy format
# z version.txt uzupelniamy zerem przed podbiciem
while ($parts.Count -lt 4) { $parts += "0" }
$parts[-1] = [string]([int]$parts[-1] + 1)
$version = $parts -join "."
Set-Content -Path $versionFile -Value $version -Encoding ascii
Write-Host "Wersja pakietu: $version (linie BPS: $($lines -join ', '))"

New-Item -ItemType Directory -Force $publishDir | Out-Null
$builtZips = @()

foreach ($line in $lines) {
    $bpsLabel = $bpsLabels[$line]
    # KAZDA linia ma wlasny katalog wyjsciowy. Wspolny katalog byl pulapka:
    # obie linie maja ten sam TargetFramework, wiec drugi build mogl uznac
    # wyjscie za aktualne i spakowac DLL zbudowany pod poprzednia linie SDK.
    $outDir = Join-Path $projectDir "bin\Release\bps$line"

    dotnet build (Join-Path $projectDir "WebconPdfSplitterAction.csproj") `
        -c Release -p:Version=$version -p:AssemblyVersion=$version -p:BpsSdk=$line `
        --output $outDir
    if ($LASTEXITCODE -ne 0) { throw "Build failed (BPS $bpsLabel)" }

    $staging = Join-Path $publishDir "staging"
    if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
    New-Item -ItemType Directory -Force $staging | Out-Null

    # DLL pluginu + zaleznosci NuGet; biblioteki WEBCON SDK dostarcza host BPS
    Copy-Item (Join-Path $outDir "WebconPdfSplitterAction.dll") $staging
    Copy-Item (Join-Path $outDir "Newtonsoft.Json.dll") $staging
    Copy-Item (Join-Path $projectDir "WebconPdfSplitterAction.json") $staging

    # nazwa ZIP-a zawiera linie BPS i wersje, zeby bylo widac, ktora paczka
    # jest na ktory serwer
    $zipPath = Join-Path $publishDir "WebconPdfSplitterAction-$bpsLabel-$version.zip"
    if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
    # stara paczka bez wersji w nazwie mylila - usun, jesli jeszcze lezy
    $legacyZip = Join-Path $publishDir "WebconPdfSplitterAction.zip"
    if (Test-Path $legacyZip) { Remove-Item -Force $legacyZip }
    Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $zipPath
    Remove-Item -Recurse -Force $staging

    $builtZips += $zipPath
}

Write-Host ""
Write-Host "Pakiety gotowe (wersja $version):"
$builtZips | ForEach-Object { Write-Host "  $_" }
