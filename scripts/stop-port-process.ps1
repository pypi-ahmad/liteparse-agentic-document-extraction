# Force-stops whatever process is listening on $Port before launch.cmd starts
# the app, so a stale run does not block the fixed port. Walks up the process
# tree to kill the outermost launcher (uv.exe -> liteparse-ade.exe/python.exe)
# rather than just the leaf process, so no orphaned wrapper is left running.
#
# Hazard: the walk only climbs past ancestors that match $appProcessNames and
# whose command line contains $ProjectRoot; it does not require the *original*
# listener itself to match anything. If an unrelated process happens to be
# listening on $Port, that process is still killed outright.
param(
    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 65535)]
    [int]$Port,

    [Parameter(Mandatory = $true)]
    [string]$ProjectRoot
)

$ErrorActionPreference = "Stop"
$appProcessNames = @("python.exe", "liteparse-ade.exe", "uv.exe")
$listenerPids = @(
    Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
)

foreach ($listenerPid in $listenerPids) {
    $rootProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $listenerPid"

    # Keep climbing to the parent only while it looks like one of this
    # project's own launcher processes; stop and kill the last process that
    # matched (which may be the original listener itself, unconditionally).
    while ($rootProcess.ParentProcessId) {
        $parent = Get-CimInstance Win32_Process `
            -Filter "ProcessId = $($rootProcess.ParentProcessId)" `
            -ErrorAction SilentlyContinue
        if (
            -not $parent -or
            $parent.Name -notin $appProcessNames -or
            $parent.CommandLine -notlike "*$ProjectRoot*"
        ) {
            break
        }
        $rootProcess = $parent
    }

    Write-Host "Stopping process tree $($rootProcess.ProcessId) on port $Port..."
    & taskkill.exe /PID $rootProcess.ProcessId /T /F *> $null
}

$deadline = [DateTime]::UtcNow.AddSeconds(10)
do {
    $listener = Get-NetTCPConnection `
        -State Listen `
        -LocalPort $Port `
        -ErrorAction SilentlyContinue
    if (-not $listener) {
        exit 0
    }
    Start-Sleep -Milliseconds 200
} while ([DateTime]::UtcNow -lt $deadline)

$remainingPids = ($listener | Select-Object -ExpandProperty OwningProcess -Unique) -join ", "
Write-Error "Port $Port is still occupied by process(es): $remainingPids"
exit 1
