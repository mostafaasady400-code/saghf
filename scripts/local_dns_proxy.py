"""
Local DNS-Resolving HTTP/HTTPS CONNECT Proxy
Routes all HTTP/HTTPS requests resolving domain names through 8.8.8.8 / 1.1.1.1
to bypass local ISP DNS resolution failures.
"""
import socket
import struct
import threading
import sys

DNS_SERVERS = ['8.8.8.8', '1.1.1.1', '178.22.122.100']
DNS_CACHE = {}

def resolve_custom_dns(domain):
    if domain in DNS_CACHE:
        return DNS_CACHE[domain]
    
    packet = b'\xaa\xbb\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00'
    for part in domain.split('.'):
        packet += bytes([len(part)]) + part.encode('ascii')
    packet += b'\x00\x00\x01\x00\x01'
    
    for srv in DNS_SERVERS:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(3)
            sock.sendto(packet, (srv, 53))
            data, _ = sock.recvfrom(2048)
            sock.close()
            idx = 12
            while idx < len(data) and data[idx] != 0:
                idx += 1 + data[idx]
            idx += 5
            while idx + 10 <= len(data):
                idx += 2
                rtype, rclass, ttl, rdlen = struct.unpack('!HHIH', data[idx:idx+10])
                idx += 10
                if rtype == 1 and rdlen == 4:
                    ip = socket.inet_ntoa(data[idx:idx+4])
                    DNS_CACHE[domain] = ip
                    return ip
                idx += rdlen
        except Exception:
            continue
            
    try:
        ip = socket.gethostbyname(domain)
        DNS_CACHE[domain] = ip
        return ip
    except Exception:
        return None

def pipe(src, dst):
    try:
        while True:
            data = src.recv(32768)
            if not data:
                break
            dst.sendall(data)
    except Exception:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except Exception:
            pass

def handle_client(client_sock):
    try:
        client_sock.settimeout(15)
        req = b''
        while b'\r\n\r\n' not in req:
            chunk = client_sock.recv(4096)
            if not chunk:
                break
            req += chunk
            
        if not req:
            client_sock.close()
            return
            
        first_line = req.split(b'\r\n')[0].decode('latin1', errors='ignore')
        parts = first_line.split()
        if len(parts) < 2:
            client_sock.close()
            return
            
        method, target = parts[0], parts[1]
        
        if method.upper() == 'CONNECT':
            if ':' in target:
                host, port_str = target.split(':', 1)
                port = int(port_str)
            else:
                host, port = target, 443
                
            ip = resolve_custom_dns(host)
            if not ip:
                client_sock.sendall(b'HTTP/1.1 502 Bad Gateway\r\n\r\n')
                client_sock.close()
                return
                
            remote_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            remote_sock.settimeout(30)
            remote_sock.connect((ip, port))
            client_sock.sendall(b'HTTP/1.1 200 Connection Established\r\n\r\n')
            
            # Remove timeouts for active tunnel
            client_sock.settimeout(None)
            remote_sock.settimeout(None)
            
            t1 = threading.Thread(target=pipe, args=(client_sock, remote_sock), daemon=True)
            t2 = threading.Thread(target=pipe, args=(remote_sock, client_sock), daemon=True)
            t1.start()
            t2.start()
            t1.join()
            t2.join()
        else:
            host_header = None
            for line in req.split(b'\r\n'):
                if line.lower().startswith(b'host:'):
                    host_header = line.split(b':', 1)[1].strip().decode('latin1')
                    break
            if not host_header:
                client_sock.close()
                return
            if ':' in host_header:
                host, port_str = host_header.split(':', 1)
                port = int(port_str)
            else:
                host, port = host_header, 80
                
            ip = resolve_custom_dns(host)
            if not ip:
                client_sock.sendall(b'HTTP/1.1 502 Bad Gateway\r\n\r\n')
                client_sock.close()
                return
                
            remote_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            remote_sock.settimeout(30)
            remote_sock.connect((ip, port))
            remote_sock.sendall(req)
            
            client_sock.settimeout(None)
            remote_sock.settimeout(None)
            
            t1 = threading.Thread(target=pipe, args=(client_sock, remote_sock), daemon=True)
            t2 = threading.Thread(target=pipe, args=(remote_sock, client_sock), daemon=True)
            t1.start()
            t2.start()
            t1.join()
            t2.join()
    except Exception:
        pass
    finally:
        try:
            client_sock.close()
        except Exception:
            pass

def main():
    port = 8088
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('127.0.0.1', port))
    server.listen(200)
    print(f"Local DNS-Resolving Proxy listening on 127.0.0.1:{port}", flush=True)
    
    while True:
        try:
            client, addr = server.accept()
            t = threading.Thread(target=handle_client, args=(client,), daemon=True)
            t.start()
        except KeyboardInterrupt:
            break
        except Exception:
            pass

if __name__ == '__main__':
    main()
