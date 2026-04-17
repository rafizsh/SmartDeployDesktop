# Run on the SmartDeploy SERVER as Administrator

# Allow DHCP
New-NetFirewallRule -DisplayName "SmartDeploy DHCP In" -Direction Inbound -Protocol UDP -LocalPort 67,68,60,4011 -Action Allow
New-NetFirewallRule -DisplayName "SmartDeploy DHCP Out" -Direction Outbound -Protocol UDP -LocalPort 67,68 -Action Allow

# Allow TFTP
New-NetFirewallRule -DisplayName "SmartDeploy TFTP" -Direction Inbound -Protocol UDP -LocalPort 69 -Action Allow

# Allow API server
New-NetFirewallRule -DisplayName "SmartDeploy API" -Direction Inbound -Protocol TCP -LocalPort 8000,8001,8002 -Action Allow

# Allow SMB (file sharing)
New-NetFirewallRule -DisplayName "SmartDeploy SMB" -Direction Inbound -Protocol TCP -LocalPort 445 -Action Allow

# Allow ICMP (ping)
New-NetFirewallRule -DisplayName "SmartDeploy Ping" -Direction Inbound -Protocol ICMPv4 -Action Allow

# Verify
Get-NetFirewallRule -DisplayName "SmartDeploy*" | Format-Table DisplayName, Direction, Action, Enabled