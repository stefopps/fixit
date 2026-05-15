# Single-instance FixIt: stop every python main.py from THIS folder, then start one.
# Requires elevation when restarting an elevated FixIt (matching RESTART/UAC flow).

$ErrorActionPreference = 'SilentlyContinue'
$repo = $PSScriptRoot
if (-not $repo) { $repo = (Get-Location).Path }
$d = [regex]::Escape($repo)

function Get-FixItProcesses {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -and
            ($_.CommandLine -match $d) -and
            ($_.CommandLine -match 'main\.py')
        }
}

function Get-PythonExe {
    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($cmd) { return @{ Exe = $cmd.Source; Args = @('main.py') } }
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) { return @{ Exe = $py.Source; Args = @('-3', 'main.py') } }
    return $null
}

$found = @(Get-FixItProcesses)
if ($found.Count -gt 0) {
    Write-Host "Closing $($found.Count) FixIt python process(es) from this folder..."
} else {
    Write-Host 'No FixIt running here — starting a new instance.'
}

for ($attempt = 1; $attempt -le 15; $attempt++) {
    $procs = @(Get-FixItProcesses)
    if ($procs.Count -eq 0) { break }
    foreach ($p in $procs) {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Milliseconds 600
}

$left = @(Get-FixItProcesses)
if ($left.Count -gt 0) {
    Write-Host ('ERROR: Could not stop old FixIt ({0} still running). Close it manually and retry.' -f $left.Count)
    exit 1
}

$pyInfo = Get-PythonExe
if (-not $pyInfo) {
    Write-Host 'ERROR: Neither python.exe nor py.exe found on PATH. Install Python or add it to PATH.'
    exit 1
}

Write-Host ("Starting FixIt: '{0}' {1}" -f $pyInfo.Exe, ($pyInfo.Args -join ' '))
Start-Process -FilePath $pyInfo.Exe -ArgumentList $pyInfo.Args -WorkingDirectory $repo
exit 0
