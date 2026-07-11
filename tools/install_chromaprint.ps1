param(
    [string]$Destination = (Join-Path $PSScriptRoot "..\.tools\chromaprint-1.6.0")
)

$ErrorActionPreference = "Stop"
$manifest = Get-Content (Join-Path $PSScriptRoot "chromaprint.json") | ConvertFrom-Json
$archive = Join-Path ([System.IO.Path]::GetTempPath()) $manifest.asset
Invoke-WebRequest -Headers @{ "User-Agent" = "Mariana/0.7" } -Uri $manifest.url -OutFile $archive
$actual = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $manifest.sha256) {
    Remove-Item -LiteralPath $archive -Force
    throw "Chromaprint checksum mismatch. Expected $($manifest.sha256), received $actual."
}
if (Test-Path -LiteralPath $Destination) {
    Remove-Item -LiteralPath $Destination -Recurse -Force
}
Expand-Archive -LiteralPath $archive -DestinationPath $Destination
Remove-Item -LiteralPath $archive -Force
$fpcalc = Get-ChildItem -LiteralPath $Destination -Recurse -Filter fpcalc.exe | Select-Object -First 1
if (-not $fpcalc) {
    throw "The verified archive did not contain fpcalc.exe."
}
& $fpcalc.FullName -version
