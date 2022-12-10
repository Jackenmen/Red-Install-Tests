# `ps:` doesn't include $ErrorActionPreference so gotta add it manually
# Also, that only works for cmdlets so we have to check exit code FOR EACH COMMAND.
# PowerShell 7.3 will fix this but not like we're going to have that in CI...
# https://github.com/PowerShell/PowerShell-RFC/pull/277
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$commands = @"
Set-ExecutionPolicy Bypass -Scope Process -Force
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
iex ((New-Object System.Net.WebClient).DownloadString('https://chocolatey.org/install.ps1'))
# v-- stop log spam by disabling download progress (not part of instructions)
choco feature disable -n=showDownloadProgress
# ^-- stop log spam by disabling download progress (not part of instructions)
choco upgrade git --params "/GitOnlyOnPath /WindowsTerminal" -y
choco upgrade visualstudio2022-workload-vctools -y
choco upgrade python311 -y

choco upgrade temurin11 -y
"@

ForEach ($command in $($commands -split '\r?\n'))
{
    Write-Host "$(prompt)$command"
    if (!$command -or $command.StartsWith('#'))
    {
        continue
    }
    Invoke-Expression "$command; `$output = `$?"
    if (!$output)
    {
        exit 1
    }
}
