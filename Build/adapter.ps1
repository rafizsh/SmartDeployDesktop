

# Fix the server IP to 10.10.10.1
netsh interface ipv4 set address name="Ethernet 4" static 10.10.10.1 255.255.0.0
netsh interface ipv4 set dnsservers name="Ethernet 4" static 172.16.1.26 primary

# Run firewall rules
New-NetFirewallRule -DisplayName "SmartDeploy DHCP" -Direction Inbound -Protocol UDP -LocalPort 67,68,60,4011 -Action Allow
New-NetFirewallRule -DisplayName "SmartDeploy TFTP" -Direction Inbound -Protocol UDP -LocalPort 69 -Action Allow
New-NetFirewallRule -DisplayName "SmartDeploy API" -Direction Inbound -Protocol TCP -LocalPort 8000,8001,8002 -Action Allow
New-NetFirewallRule -DisplayName "SmartDeploy SMB" -Direction Inbound -Protocol TCP -LocalPort 445 -Action Allow
New-NetFirewallRule -DisplayName "SmartDeploy Ping" -Direction Inbound -Protocol ICMPv4 -Action Allow

# Verify
ipconfig | findstr /C:"Ethernet 4" /C:"IPv4" /C:"Subnet" /C:"Gateway"