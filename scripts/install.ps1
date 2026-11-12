# A script installer: no Python required. Run with Windows PowerShell 5.1+.
[CmdletBinding()]
param(
    [ValidateSet('User', 'AllUsers')][string]$Scope,
    [string]$Directory,
    [switch]$AddToPath,
    [string]$FromDirectory
)
$ErrorActionPreference = 'Stop'
$env:PSModulePath = [IO.Path]::Combine($PSHOME, 'Modules')
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
    if ($Scope -eq 'AllUsers') { $Directory = Join-Path ([Environment]::GetFolderPath('ProgramFiles')) 'gorak' }
    else { $Directory = Join-Path $env:LOCALAPPDATA 'Programs\gorak' }
}
$Directory = [IO.Path]::GetFullPath($Directory)
if ($Scope -eq 'AllUsers') {
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'For AllUsers, open an administrator PowerShell and rerun this installer. Subsequent system updates prompt for UAC using the protected installed helper.'
    }
    $programFiles = [Environment]::GetFolderPath('ProgramFiles')
    if ($Directory -ne (Join-Path $programFiles 'gorak')) { throw 'AllUsers installations must use Program Files\gorak.' }
    $acl = New-Object Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true, $false)
    $administrators = New-Object Security.Principal.SecurityIdentifier('S-1-5-32-544')
    $acl.SetOwner($administrators)
    foreach ($sid in @('S-1-5-18', 'S-1-5-32-544')) {
        $identity = New-Object Security.Principal.SecurityIdentifier($sid)
        $acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($identity, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')))
    }
    $staging = Join-Path $programFiles ('gorak-install-' + [Guid]::NewGuid())
    [IO.Directory]::CreateDirectory($staging, $acl) | Out-Null
    $users = New-Object Security.Principal.SecurityIdentifier('S-1-5-32-545')
    $acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($users, 'ReadAndExecute', 'ContainerInherit,ObjectInherit', 'None', 'Allow')))
    [IO.Directory]::CreateDirectory($Directory, $acl) | Out-Null
    if ((Get-Item -LiteralPath $Directory).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'System installation must not be a reparse point.' }
    $actualAcl = Get-Acl -LiteralPath $Directory
    if ($actualAcl.GetOwner([Security.Principal.SecurityIdentifier]).Value -notin @('S-1-5-18', 'S-1-5-32-544')) { throw 'System installation has an untrusted owner.' }
    foreach ($rule in $actualAcl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])) {
        if ($rule.AccessControlType -eq 'Allow' -and ([int]$rule.FileSystemRights -band 0xD0156) -and
            $rule.IdentityReference.Value -notin @('S-1-5-18', 'S-1-5-32-544')) { throw 'System installation allows non-administrator writes.' }
    }
} else {
    $staging = Join-Path ([IO.Path]::GetTempPath()) ('gorak-install-' + [Guid]::NewGuid())
    New-Item -ItemType Directory -Path $staging | Out-Null
}
$oldTemp = $env:TEMP
$oldTmp = $env:TMP
try {
    if ($Scope -eq 'AllUsers') {
        $env:TEMP = $staging
        $env:TMP = $staging
        Get-ChildItem Env: | Where-Object { $_.Name -like '_PYI_*' } | ForEach-Object { Remove-Item ('Env:' + $_.Name) }
        $env:PYINSTALLER_RESET_ENVIRONMENT = '1'
    }
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
    $env:TEMP = $oldTemp
    $env:TMP = $oldTmp
    Remove-Item -LiteralPath $staging -Recurse -Force
}
