# Installed under Program Files by gorak. Never execute a caller-supplied candidate.
[CmdletBinding()]
param([int]$WaitPid = 0)
$ErrorActionPreference = 'Stop'
# Avoid user-controlled module autoload paths in the elevated process.
$env:PSModulePath = [IO.Path]::Combine($PSHOME, 'Modules')
$root = Join-Path ([Environment]::GetFolderPath('ProgramFiles')) 'gorak'
if ([IO.Path]::GetFullPath($PSScriptRoot) -ne $root) { throw 'Unexpected system installation directory.' }
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'The system updater requires administrator approval.'
}
if ((Get-Item -LiteralPath $root).Attributes -band [IO.FileAttributes]::ReparsePoint) {
    throw 'System installation must not be a reparse point.'
}
if ($WaitPid) { Wait-Process -Id $WaitPid -Timeout 60 -ErrorAction SilentlyContinue }
# This fresh directory inherits only administrator/SYSTEM write access from Program Files.
$staging = Join-Path ([Environment]::GetFolderPath('ProgramFiles')) ('gorak-update-' + [Guid]::NewGuid())
$acl = New-Object Security.AccessControl.DirectorySecurity
$acl.SetAccessRuleProtection($true, $false)
foreach ($sid in @('S-1-5-18', 'S-1-5-32-544')) {
    $identity = New-Object Security.Principal.SecurityIdentifier($sid)
    $rule = New-Object Security.AccessControl.FileSystemAccessRule($identity, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
    $acl.AddAccessRule($rule)
}
[IO.Directory]::CreateDirectory($staging, $acl) | Out-Null
try {
    # The one-file bootloader and every probe must also extract into protected storage.
    $env:TEMP = $staging
    $env:TMP = $staging
    Get-ChildItem Env: | Where-Object { $_.Name -like '_PYI_*' } | ForEach-Object { Remove-Item ('Env:' + $_.Name) }
    $env:PYINSTALLER_RESET_ENVIRONMENT = '1'
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $release = Invoke-RestMethod 'https://api.github.com/repos/dougwhite/gorak/releases/latest'
    if ($release.draft -or $release.tag_name -notmatch '^v[0-9][A-Za-z0-9.+-]*$') { throw 'Invalid release tag.' }
    $base = 'https://github.com/dougwhite/gorak/releases/download/' + $release.tag_name
    $manifest = Invoke-RestMethod "$base/gorak-release.json"
    $asset = $manifest.assets.'windows-x64'
    if ($manifest.schema -ne 1 -or $manifest.tag -ne $release.tag_name -or
        $asset.name -ne 'gorak-windows-x64.exe' -or $asset.sha256 -cnotmatch '^[0-9a-f]{64}$') {
        throw 'Invalid release manifest.'
    }
    $candidate = Join-Path $staging 'gorak.exe'
    Invoke-WebRequest -UseBasicParsing "$base/gorak-windows-x64.exe" -OutFile $candidate
    if ((Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash.ToLowerInvariant() -ne $asset.sha256) {
        throw 'Executable checksum mismatch; installation unchanged.'
    }
    $info = & $candidate --_build-info | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0 -or $info.tag -ne $manifest.tag -or
        $info.version -ne $manifest.version -or $info.platform -ne 'windows-x64') {
        throw 'Unexpected executable build identity.'
    }
    & $candidate --_install --root $root --scope system --sha256 $asset.sha256
    if ($LASTEXITCODE -ne 0) { throw 'gorak system update failed.' }
} catch {
    $message = 'gorak system update failed: ' + $_.Exception.Message
    Set-Content -LiteralPath (Join-Path $root 'update-result.txt') -Value $message -Encoding UTF8
    Write-Error $message
    exit 1
} finally {
    Remove-Item -LiteralPath $staging -Recurse -Force
}
