# Disable Network Location wizard prompt when
reg add 'HKLM\SYSTEM\CurrentControlSet\Control\Network\NewNetworkWindowOff' /f

# Disable Windows Update and auto-download of MS Store updates
reg add 'HKLM\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU' /v NoAutoUpdate /t REG_DWORD /d 1 /f
reg add 'HKLM\SOFTWARE\Policies\Microsoft\WindowsStore' /v AutoDownload /t REG_DWORD /d 2 /f
reg add 'HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsStore\WindowsUpdate' /v AutoDownload /t REG_DWORD /d 2 /f

# Download gsudo to allow to strip elevation over SSH
curl.exe -Lo $env:TEMP\gsudo.portable.zip https://github.com/gerardog/gsudo/releases/download/v2.6.1/gsudo.portable.zip
mkdir $env:TEMP\gsudo
tar.exe -C $env:TEMP\gsudo -xf $env:TEMP\gsudo.portable.zip
Copy-Item $env:TEMP\gsudo\x64 C:\gsudo -Recurse

# Install SSH server
# https://github.com/PowerShell/Win32-OpenSSH/wiki/Install-Win32-OpenSSH-Using-MSI
# This is faster than `Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0`
# because it's an optional FOD package - it requires re-applying Windows updates:
# https://www.elevenforum.com/t/why-is-openssh-an-optional-feature-and-takes-ages-to-install-add-optional-feature.37224/
$ssh_base_version = '10.0.0.0'
$base_download_url = 'https://github.com/PowerShell/Win32-OpenSSH/releases/download/'
$base_download_url += "$($ssh_base_version)p2-Preview"
$msi_url = if ([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture -eq 'Arm64') {
    "$base_download_url/OpenSSH-ARM64-v$ssh_base_version.msi"
} else {
    "$base_download_url/OpenSSH-Win64-v$ssh_base_version.msi"
}
curl.exe -Lo $env:TEMP\openssh.msi $msi_url
msiexec /i $env:TEMP\openssh.msi
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
