# Start a command that outlives this terminal and any console: no console at all (DETACHED_PROCESS), a process group
# of its own (Ctrl+C / Ctrl+Break of other consoles never reach it), started by WMI (outside this terminal's job).
#   powershell -File launch_detached.ps1 "python -u world.py --instances 3 > world\world_run.log 2>&1"
param([Parameter(Mandatory = $true)][string]$Command)
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$startup = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{ CreateFlags = [uint32](0x8 -bor 0x200); ShowWindow = [uint16]0 }
$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
    CommandLine = "cmd.exe /c `"cd /d $dir && $Command`""; CurrentDirectory = $dir; ProcessStartupInformation = $startup }
"started: return $($r.ReturnValue), pid $($r.ProcessId)"
