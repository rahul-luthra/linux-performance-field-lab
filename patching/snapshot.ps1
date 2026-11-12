param(
    [Parameter(Mandatory)][ValidateSet('patch-canary','patch-peer')][string] $Name,
    [Parameter(Mandatory)][ValidateSet('take','restore')][string] $Action
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$vbox = Join-Path $env:ProgramFiles 'Oracle\VirtualBox\VBoxManage.exe'
$snapshot = 'pre-patch-baseline'
$path = Join-Path $env:USERPROFILE "VirtualBox VMs\$Name\$Name.vbox"

function Invoke-VBox {
    & $vbox @args
    if ($LASTEXITCODE -ne 0) { throw "VirtualBox failed during $($args[0]) for $Name." }
}

$timer = [System.Diagnostics.Stopwatch]::StartNew()
do {
    $state = Invoke-VBox showvminfo $Name --machinereadable
    $configured = @($state -match '^CfgFile=')[0].Substring(9).TrimEnd('"').Replace('\\','\')
    if ($configured -ine $path) { throw "Unexpected VM path for $Name." }
    if ($state -contains 'VMState="poweroff"') { break }
    Start-Sleep -Seconds 1
} while ($timer.Elapsed.TotalSeconds -lt 65)
if ($state -notcontains 'VMState="poweroff"') { throw "$Name did not shut down cleanly." }

if ($Action -eq 'take') {
    Invoke-VBox snapshot $Name take $snapshot '--description=Healthy lab state and pre-change package' | Out-Null
} else {
    $snapshots = Invoke-VBox snapshot $Name list --machinereadable
    if (-not ($snapshots -match '^SnapshotName(?:-\d+)*="pre-patch-baseline"$')) {
        throw "Expected baseline snapshot for $Name."
    }
    Invoke-VBox snapshot $Name restore $snapshot | Out-Null
}
Invoke-VBox startvm $Name --type=headless | Out-Null
[pscustomobject]@{ node=$Name; action=$Action; snapshot=$snapshot; seconds=[math]::Round($timer.Elapsed.TotalSeconds,3) } |
    ConvertTo-Json -Compress
