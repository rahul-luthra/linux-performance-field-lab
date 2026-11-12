param(
    [Parameter(Mandatory)][string] $HostAddress,
    [Parameter(Mandatory)][string] $ControllerAddress,
    [Parameter(Mandatory)][string] $Image,
    [Parameter(Mandatory)][string] $ImageSha256,
    [switch] $Resume
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$vbox = Join-Path $env:ProgramFiles 'Oracle\VirtualBox\VBoxManage.exe'
$base = Join-Path $env:USERPROFILE 'VirtualBox VMs'
$firewallName = 'Patch rollout lab scoped ports'
$targets = [ordered]@{
    'patch-canary' = @(2321, 8321)
    'patch-peer' = @(2322, 8322)
}

function Invoke-VBox {
    & $vbox @args
    if ($LASTEXITCODE -ne 0) { throw "VBoxManage failed on $($args[0]) $($args[1])" }
}

if (!(Get-NetIPAddress -AddressFamily IPv4 -IPAddress $HostAddress -ErrorAction SilentlyContinue)) {
    throw 'The requested bind address is not configured on this host.'
}
if ((Get-FileHash -LiteralPath $Image -Algorithm SHA256).Hash -ine $ImageSha256) {
    throw 'The source image does not match its expected SHA-256.'
}
$registered = Invoke-VBox list vms
$reservedPorts = 2321, 2322, 8321, 8322
if (Get-NetTCPConnection -State Listen | Where-Object LocalPort -in $reservedPorts) {
    throw 'At least one of the reserved TCP ports is already listening.'
}
if ((Get-NetFirewallRule -DisplayName $firewallName -ErrorAction SilentlyContinue) -and !$Resume) {
    throw 'The firewall rule already exists. Review the existing lab before running again.'
}
foreach ($name in $targets.Keys) {
    if (!$Resume -and ($registered -match ('^"' + [regex]::Escape($name) + '"\s') -or
        (Test-Path -LiteralPath (Join-Path $base $name)))) {
        throw "VM name or folder already exists for $name."
    }
    if (!(Test-Path -LiteralPath (Join-Path $PSScriptRoot "$name.iso") -PathType Leaf)) {
        throw "Missing NoCloud ISO for $name."
    }
}

$firewall = @{
    DisplayName = $firewallName
    Direction = 'Inbound'
    Action = 'Allow'
    Protocol = 'TCP'
    LocalAddress = $HostAddress
    LocalPort = $reservedPorts
    RemoteAddress = @($HostAddress, $ControllerAddress)
}
if (!(Get-NetFirewallRule -DisplayName $firewallName -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule @firewall | Out-Null
}

foreach ($name in $targets.Keys) {
    $folder = Join-Path $base $name
    $disk = Join-Path $folder "$name.vdi"
    $imageCopy = Join-Path $PSScriptRoot "$name-source.vmdk"
    $seed = Join-Path $PSScriptRoot "$name.iso"
    $serial = Join-Path $PSScriptRoot "$name-serial.log"
    $sshPort, $httpPort = $targets[$name]
    $settings = @(
        '--cpus=1', '--memory=1024', '--firmware=efi64', '--chipset=piix3', '--ioapic=on',
        '--graphicscontroller=vmsvga', '--vram=16', '--nic1=nat', '--cable-connected1=on',
        '--boot1=disk', '--boot2=none', '--boot3=none', '--boot4=none',
        '--uart1', '0x3F8', '4', '--uart-mode1', 'file', $serial,
        "--nat-pf1=lab-ssh,tcp,$HostAddress,$sshPort,,22", "--nat-pf1=lab-http,tcp,$HostAddress,$httpPort,,8080"
    )

    if ($registered -match ('^"' + [regex]::Escape($name) + '"\s')) {
        $info = Invoke-VBox showvminfo $name --machinereadable
        $configuredPath = ($info -match '^CfgFile=').Substring(9).TrimEnd('"').Replace('\\','\')
        $forwarding = ($info -match '^Forwarding\(\d+\)=') -replace '^Forwarding\(\d+\)=',''
        if ($info -notcontains 'VMState="poweroff"' -or
            $configuredPath -ine (Join-Path $folder "$name.vbox") -or
            $forwarding -notcontains ('"lab-ssh,tcp,{0},{1},,22"' -f $HostAddress,$sshPort) -or
            $forwarding -notcontains ('"lab-http,tcp,{0},{1},,8080"' -f $HostAddress,$httpPort) -or
            ($info -match '^storagecontrollername\d+=')) {
            throw "Cannot resume $name. Expected the partial powered-off lab VM with no storage controller."
        }
    } else {
        Invoke-VBox createvm "--name=$name" --platform-architecture=x86 --ostype=Ubuntu_64 "--basefolder=$base" --register
        Invoke-VBox modifyvm $name @settings
    }
    if (!(Test-Path -LiteralPath $imageCopy)) {
        Copy-Item -LiteralPath $Image -Destination $imageCopy
    }
    if ((Get-FileHash -LiteralPath $imageCopy -Algorithm SHA256).Hash -ine $ImageSha256) {
        throw "Staged source image checksum mismatch for $name."
    }
    if (Test-Path -LiteralPath $disk) {
        if (!(Invoke-VBox showmediuminfo disk $disk | Select-String '^Parent UUID:\s+base$')) {
            throw "Expected an independent VDI for $name."
        }
    } else {
        Invoke-VBox clonemedium $imageCopy $disk disk --format=VDI --variant=Standard
    }
    Invoke-VBox storagectl $name --name=SATA --add=sata --controller=IntelAhci --portcount=2 --bootable=on
    Invoke-VBox storageattach $name --storagectl=SATA --port=0 --device=0 --type=hdd "--medium=$disk"
    Invoke-VBox storageattach $name --storagectl=SATA --port=1 --device=0 --type=dvddrive "--medium=$seed"
    Invoke-VBox startvm $name --type=headless
}
