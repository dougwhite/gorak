# A script installer: no Python required. Run with Windows PowerShell 5.1+.
[CmdletBinding()]
param(
    [ValidateSet('User', 'AllUsers')][string]$Scope,
    [string]$Directory,
    [switch]$AddToPath,
    [string]$FromDirectory
)
$ErrorActionPreference = 'Stop'
if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64') {
    throw 'This installer supports Windows x64 only.'
}
if (-not $Scope) {
    $choice = Read-Host 'Install gorak: [1] Just for me (default), [2] Everyone'
    if ($choice -eq '2') { $Scope = 'AllUsers' } else { $Scope = 'User' }
    if (-not $PSBoundParameters.ContainsKey('AddToPath')) {
        $AddToPath = (Read-Host 'Add gorak to PATH? [y/N]') -match '^[yY]'
    }
}
if (-not $Directory) {
    if ($Scope -eq 'AllUsers') { $Directory = Join-Path $env:ProgramFiles 'gorak' }
    else { $Directory = Join-Path $env:LOCALAPPDATA 'Programs\gorak' }
}
$Directory = [IO.Path]::GetFullPath($Directory)
if ($Scope -eq 'AllUsers') {
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        # Windows paths cannot contain double quotes; quote each path for -File.
        $arguments = '-NoProfile -ExecutionPolicy Bypass -File "{0}" -Scope AllUsers -Directory "{1}"' -f $PSCommandPath, $Directory
        if ($AddToPath) { $arguments += ' -AddToPath' }
        if ($FromDirectory) { $arguments += ' -FromDirectory "{0}"' -f ([IO.Path]::GetFullPath($FromDirectory)) }
        $process = Start-Process powershell.exe -Verb RunAs -ArgumentList $arguments -Wait -PassThru
        exit $process.ExitCode
    }
}
$staging = Join-Path ([IO.Path]::GetTempPath()) ('gorak-install-' + [Guid]::NewGuid())
New-Item -ItemType Directory -Path $staging | Out-Null
try {
    $asset = 'gorak-windows-x64.exe'
    if ($FromDirectory) {
        $manifest = Get-Content -LiteralPath (Join-Path $FromDirectory 'gorak-release.json') -Raw | ConvertFrom-Json
        Copy-Item -LiteralPath (Join-Path $FromDirectory $asset) -Destination (Join-Path $staging $asset)
    } else {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $release = Invoke-RestMethod 'https://api.github.com/repos/dougwhite/gorak/releases/latest'
        if ($release.draft -or $release.tag_name -notmatch '^v[0-9][A-Za-z0-9.+-]*$') { throw 'Invalid release tag.' }
        $base = 'https://github.com/dougwhite/gorak/releases/download/' + $release.tag_name
        $manifest = Invoke-RestMethod "$base/gorak-release.json"
        if ($manifest.tag -ne $release.tag_name) { throw 'Mismatched release manifest.' }
        Invoke-WebRequest -UseBasicParsing "$base/$asset" -OutFile (Join-Path $staging $asset)
    }
    $entry = $manifest.assets.'windows-x64'
    if ($manifest.schema -ne 1 -or $entry.name -ne $asset -or $entry.sha256 -cnotmatch '^[0-9a-f]{64}$') {
        throw 'Unsupported release manifest.'
    }
    $candidate = Join-Path $staging $asset
    if ((Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.sha256) {
        throw 'Executable checksum mismatch; installation unchanged.'
    }
    $installScope = if ($Scope -eq 'AllUsers') { 'system' } else { 'user' }
    & $candidate --_install --root $Directory --scope $installScope --sha256 $entry.sha256
    if ($LASTEXITCODE -ne 0) { throw 'gorak installation failed.' }
    if ($AddToPath) {
        $target = if ($Scope -eq 'AllUsers') { 'Machine' } else { 'User' }
        $bin = Join-Path $Directory 'bin'
        $current = [Environment]::GetEnvironmentVariable('Path', $target)
        $entries = @($current -split ';' | Where-Object { $_ })
        if ($entries -notcontains $bin) {
            [Environment]::SetEnvironmentVariable('Path', (($entries + $bin) -join ';'), $target)
        }
        Write-Host 'PATH updated. Open a new terminal to use gorak.'
    } else {
        Write-Host ('Add this directory to PATH if desired: ' + (Join-Path $Directory 'bin'))
    }
} finally {
    Remove-Item -LiteralPath $staging -Recurse -Force
}
