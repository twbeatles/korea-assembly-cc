param(
    [Parameter(Mandatory = $true)]
    [string]$Path,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9A-Fa-f ]+$')]
    [string]$CertificateThumbprint,

    [Parameter(Mandatory = $false)]
    [ValidatePattern('^https://')]
    [string]$TimestampUrl = 'https://timestamp.digicert.com'
)

$ErrorActionPreference = 'Stop'
$resolvedPath = (Resolve-Path -LiteralPath $Path).Path
if ([System.IO.Path]::GetExtension($resolvedPath) -ine '.exe') {
    throw 'Authenticode target must be an .exe file.'
}

$signTool = Get-Command 'signtool.exe' -ErrorAction Stop
& $signTool.Source sign /sha1 ($CertificateThumbprint -replace ' ', '') /fd SHA256 /tr $TimestampUrl /td SHA256 $resolvedPath
if ($LASTEXITCODE -ne 0) {
    throw "signtool failed with exit code $LASTEXITCODE"
}

$signature = Get-AuthenticodeSignature -LiteralPath $resolvedPath
if ($signature.Status -ne 'Valid') {
    throw "Authenticode verification failed: $($signature.Status)"
}

Write-Host "Authenticode signature verified: $resolvedPath"
