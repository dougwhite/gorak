# Offline acceptance of the elevated helper using disposable roots and local bytes.
param([Parameter(Mandatory=$true)][string]$Binary)
$ErrorActionPreference = 'Stop'
$Binary = [IO.Path]::GetFullPath($Binary)
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this isolated helper acceptance in an administrator shell.'
}
$base = Join-Path ([IO.Path]::GetTempPath()) ('gorak-system-proof-' + [Guid]::NewGuid())
New-Item -ItemType Directory -Path $base | Out-Null
try {
    $root = Join-Path $base 'gorak'
    $hash = (Get-FileHash -LiteralPath $Binary -Algorithm SHA256).Hash.ToLowerInvariant()
    $info = & $Binary --_build-info | ConvertFrom-Json
    if ($LASTEXITCODE) { throw 'Build identity failed.' }
    & $Binary --_install --root $root --scope user --sha256 $hash
    if ($LASTEXITCODE) { throw 'Fixture installation failed.' }
    $helper = Join-Path $root 'system-update.ps1'
    $source = Get-Content -LiteralPath (Join-Path $PSScriptRoot '../src/gorak/install_scripts/system-update.ps1') -Raw
    # Substitute only location policy and final worker scope. The helper's ACL,
    # staging, environment, download verification, and execution remain unchanged.
    $source = $source.Replace("[Environment]::GetFolderPath('ProgramFiles')", ("'" + $base.Replace("'", "''") + "'"))
    $source = $source.Replace('--scope system', '--scope user')
    Set-Content -LiteralPath $helper -Value $source
    $context = @{
        binary = $Binary; helper = $helper; root = $root; corrupt = $false
        manifest = @{ schema = 1; tag = $info.tag; version = $info.version; assets = @{
            'windows-x64' = @{ name = 'gorak-windows-x64.exe'; sha256 = $hash }
        }}
    }
    $contextFile = Join-Path $base 'context.json'
    $env:GORAK_HELPER_PROOF = $contextFile
    $wrapper = Join-Path $base 'wrapper.ps1'
    @'
$ErrorActionPreference = 'Stop'
$context = Get-Content -LiteralPath $env:GORAK_HELPER_PROOF -Raw | ConvertFrom-Json
function Invoke-RestMethod([string]$Uri) {
    if ($Uri -eq 'https://api.github.com/repos/dougwhite/gorak/releases/latest') {
        return @{ draft = $false; tag_name = $context.manifest.tag }
    }
    if ($Uri -eq ('https://github.com/dougwhite/gorak/releases/download/' + $context.manifest.tag + '/gorak-release.json')) { return $context.manifest }
    throw 'Unexpected metadata request.'
}
function Invoke-WebRequest([switch]$UseBasicParsing, [string]$Uri, [string]$OutFile) {
    if ($Uri -ne ('https://github.com/dougwhite/gorak/releases/download/' + $context.manifest.tag + '/gorak-windows-x64.exe')) { throw 'Unexpected binary request.' }
    $directory = Split-Path $OutFile
    if ($env:TEMP -ne $directory -or $env:TMP -ne $directory -or $env:PYINSTALLER_RESET_ENVIRONMENT -ne '1') { throw 'Unprotected extraction environment.' }
    $acl = Get-Acl -LiteralPath $directory
    if (-not $acl.AreAccessRulesProtected) { throw 'Staging inherits untrusted permissions.' }
    foreach ($rule in $acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])) {
        if ($rule.AccessControlType -eq 'Allow' -and $rule.IdentityReference.Value -notin @('S-1-5-18', 'S-1-5-32-544')) { throw 'Staging is accessible to non-administrators.' }
    }
    Copy-Item -LiteralPath $context.binary -Destination $OutFile
    if ($context.corrupt) { [IO.File]::AppendAllText($OutFile, 'corrupt') }
}
& $context.helper
'@ | Set-Content -LiteralPath $wrapper
    foreach ($corrupt in @($false, $true)) {
        $context.corrupt = $corrupt
        $context | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $contextFile
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $wrapper
        if ((-not $corrupt -and $LASTEXITCODE -ne 0) -or ($corrupt -and $LASTEXITCODE -ne 1)) { throw 'Unexpected helper result.' }
        if ((Get-FileHash -LiteralPath (Join-Path $root 'bin/gorak.exe') -Algorithm SHA256).Hash.ToLowerInvariant() -ne $hash) { throw 'Installed binary changed unexpectedly.' }
        if ($corrupt -and (Get-Content -LiteralPath (Join-Path $root 'update-result.txt') -Raw) -notmatch 'checksum mismatch') { throw 'Expected checksum refusal.' }
    }
    Write-Host 'PASS: protected helper staging, extraction environment, verified install, and checksum refusal'
} finally {
    Remove-Item Env:GORAK_HELPER_PROOF -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $base -Recurse -Force
}
