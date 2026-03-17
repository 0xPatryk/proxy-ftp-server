# FTP Proxy Server

A lightweight Python FTP proxy designed to bridge cloud automation tools (specifically **Make.com**) and strict enterprise FTP servers.

## The Problem

1. **Make.com Requirements:** Make.com only supports **Passive Mode** FTP. In passive mode, the client initiates connections to random high-numbered data ports on the server. 
2. **Strict Enterprise Firewalls:** Enterprise networks often block incoming connections on random high-numbered data ports. They also typically require whitelisting a single static IP address for incoming connections, which conflicts with Make.com's dynamic, frequently-changing IPs.
3. **NAT Issues:** Internal enterprise FTP servers behind Network Address Translation (NAT) often fail to report their correct external IP address (`MasqueradeAddress`) to the client, causing connections to drop.

## The Solution

This proxy server acts as an intelligent intermediary. It resolves the firewall conflicts by:

- **Controlling Data Ports:** Enforcing a specifically defined, narrow range of passive ports (`PASV_MIN` to `PASV_MAX`) that enterprise firewall administrators can confidently whitelist.
- **Handling NAT properly:** Forcing the correct external public IP (`PUBLIC_IP`) to be returned to Make.com during the connection handshake.
- **Stable Static IP:** Providing a stable ingress point. Make.com connects to the proxy's IP, and the proxy then forwards the commands to the target enterprise server.

## Architecture Flow

1. **Make.com** connects to the **Proxy** using the proxy's local credentials (`LOCAL_USER` / `LOCAL_PASS`).
2. The **Proxy** provides the exact data ports and IP required by Make.com for the passive mode transfer.
3. The **Proxy** actively logs into the **Target Enterprise FTP Server** using the upstream credentials (`TARGET_USER` / `TARGET_PASS`) and transparently translates all filesystem operations.

## Configuration (.env)

Set the following environment variables to run the proxy:

### Upstream (The Enterprise Server)
- `TARGET_HOST`: IP or domain of the final destination FTP server.
- `TARGET_PORT`: Upstream FTP port (default: 21).
- `TARGET_USER`: Target FTP username.
- `TARGET_PASS`: Target FTP password.

### Proxy (What Make.com uses)
- `LOCAL_USER`: The username Make.com will use to log into the proxy.
- `LOCAL_PASS`: The password Make.com will use.
- `PUBLIC_IP`: The external public IP address of the machine running the proxy.
- `PASV_MIN`: The starting port for passive data transfers (e.g., `41000`).
- `PASV_MAX`: The ending port for passive data transfers (e.g., `41011`).
