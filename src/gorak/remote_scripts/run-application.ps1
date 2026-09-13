param([Parameter(Mandatory=$true)][string]$Request)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$temporary = $null
try {
    $config = Get-Content -LiteralPath $Request -Raw -Encoding UTF8 | ConvertFrom-Json
    Remove-Item -LiteralPath $Request
    $root = Split-Path -Parent $MyInvocation.MyCommand.Path
    foreach ($property in $config.environment.PSObject.Properties) {
        [Environment]::SetEnvironmentVariable($property.Name, [string]$property.Value, 'Process')
    }
    if (-not $env:II_SYSTEM) { $env:II_SYSTEM = 'C:\Program Files\Ingres\ingresWD' }
    $env:PATH = "$env:II_SYSTEM\ingres\bin;$env:II_SYSTEM\ingres\utility;$env:PATH"
    $env:LIB = "$env:II_SYSTEM\ingres\lib;$env:LIB"
    $env:INCLUDE = "$env:II_SYSTEM\ingres\files;$env:INCLUDE"
    $env:II_W4GLAPPS_SYS = "$env:II_SYSTEM\ingres\w4glapps\"
    $token = [guid]::NewGuid().ToString('N')
    if ($config.trace_mode -eq 'temp') {
        $temporary = Join-Path ([IO.Path]::GetTempPath()) "gorak-$token"
        $traceRoot = $temporary
    } elseif ($config.trace_dir) { $traceRoot = $config.trace_dir
    } else { $traceRoot = Join-Path $root 'traces' }
    if (-not [IO.Path]::IsPathRooted($traceRoot)) { throw 'Trace directory must be absolute' }
    New-Item -ItemType Directory -Force -Path $traceRoot | Out-Null
    $trace = Join-Path $traceRoot "$($config.application)-$env:USERNAME-$token.log"
    $report = Join-Path $traceRoot "$($config.application)-$token.xml"
    if ($config.testing) {
        $env:OR_UNITTEST_GEN_XML_STATS = 'true'
        $env:OR_UNITTEST_STATSFILE_XML = $report
        $env:OR_UNITTEST_STATSFILE = Join-Path $traceRoot "$token.stats.log"
    }
    $arguments = @('rundbapp', $config.database, $config.application, '-nowindows', '-TALL,logonly', "-L$trace")
    if ($config.component) { $arguments += "-c$($config.component)" }
    foreach ($argument in $arguments) {
        if ($argument -match '["\r\n]' -or $argument.Contains([char]0)) { throw 'Unsupported character in runner argument' }
    }
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo.FileName = "$env:II_SYSTEM\ingres\bin\w4gldev.exe"
    $process.StartInfo.Arguments = 'rundbapp "' + $config.database + '" "' + $config.application + '" -nowindows -TALL,logonly -L"' + $trace + '"'
    if ($config.component) { $process.StartInfo.Arguments += ' -c' + $config.component }
    $process.StartInfo.UseShellExecute = $false
    $process.StartInfo.CreateNoWindow = $true
    $process.StartInfo.RedirectStandardOutput = $true
    $process.StartInfo.RedirectStandardError = $true
    [void]$process.Start()
    $stdout = $process.StandardOutput.ReadToEndAsync()
    $stderr = $process.StandardError.ReadToEndAsync()
    $timedOut = -not $process.WaitForExit([int]$config.timeout * 1000)
    if ($timedOut) {
        & taskkill /PID $process.Id /T /F | Out-Null
        if (-not $process.WaitForExit(5000)) { throw 'Timed-out process did not terminate' }
    }
    $process.WaitForExit()
    $code = if ($timedOut) { 124 } else { $process.ExitCode }
    $traceText = if (Test-Path -LiteralPath $trace) { [string](Get-Content -LiteralPath $trace -Raw) } else { '' }
    $reportText = if (Test-Path -LiteralPath $report) { [string](Get-Content -LiteralPath $report -Raw -Encoding UTF8) } else { '' }
    $result = @{ exit_code=$code; timed_out=$timedOut; trace=$traceText; report=$reportText; trace_path=$trace; output=($stdout.Result + $stderr.Result) }
    $process.Dispose()
    $result | ConvertTo-Json -Compress
} finally {
    if ($temporary -and (Test-Path -LiteralPath $temporary)) { Remove-Item -LiteralPath $temporary -Recurse -Force }
}
