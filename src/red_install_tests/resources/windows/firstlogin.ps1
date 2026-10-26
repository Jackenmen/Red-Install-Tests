# Disable screen timeout
powercfg.exe /change monitor-timeout-ac 0

# Disable Network Location wizard prompt when
reg add 'HKLM\SYSTEM\CurrentControlSet\Control\Network\NewNetworkWindowOff' /f

# Disable Windows Update and auto-download of MS Store updates
reg add 'HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU' /v NoAutoUpdate /t REG_DWORD /d 1 /f
reg add 'HKLM\SOFTWARE\Policies\Microsoft\WindowsStore' /v AutoDownload /t REG_DWORD /d 2 /f
reg add 'HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsStore\WindowsUpdate' /v AutoDownload /t REG_DWORD /d 2 /f

$cidata_dir = (Get-Volume -FileSystemLabel cidata).DriveLetter + ":"

# Copy gsudo over to allow to strip elevation over SSH
Copy-Item $cidata_dir\gsudo C:\gsudo -Recurse

# Install SSH server
# https://github.com/PowerShell/Win32-OpenSSH/wiki/Install-Win32-OpenSSH-Using-MSI
msiexec /i "$cidata_dir\openssh.msi"
[Environment]::SetEnvironmentVariable("Path", [Environment]::GetEnvironmentVariable("Path",[System.EnvironmentVariableTarget]::Machine) + ';' + ${Env:ProgramFiles} + '\OpenSSH', [System.EnvironmentVariableTarget]::Machine)

# Configure SSH key
$authorizedKey = Get-Content -Path A:\ssh.key.pub
Add-Content -Force -Path $env:ProgramData\ssh\administrators_authorized_keys -Value $authorizedKey
icacls.exe ""$env:ProgramData\ssh\administrators_authorized_keys"" /inheritance:r /grant ""Administrators:F"" /grant ""SYSTEM:F""

# Start SSH server
Start-Service sshd
Set-Service -Name sshd -StartupType 'Automatic'
# Confirm the Firewall rule is configured. It should be created automatically by setup. Run the following to verify
if (!(Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH Server (sshd)' -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22
}

# Set all network connections to private to allow SSH connections
Get-NetConnectionProfile | Set-NetConnectionProfile -NetworkCategory Private
