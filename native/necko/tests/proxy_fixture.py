"""Local-only HTTP forward and CONNECT proxy for transport tests."""
import select
import socket
import socketserver
from urllib.parse import urlsplit


class ProxyHandler(socketserver.BaseRequestHandler):
    def handle(self):
        data=b""
        while b"\r\n\r\n" not in data:
            part=self.request.recv(4096)
            if not part:return
            data+=part
            if len(data)>65536:return
        head,tail=data.split(b"\r\n\r\n",1)
        first,*headers=head.split(b"\r\n")
        method,target,version=first.decode().split(" ",2)
        address=urlsplit("//"+target if method=="CONNECT" else target)
        if address.hostname!="127.0.0.1":return
        with socket.create_connection((address.hostname,address.port),timeout=3) as upstream:
            if method=="CONNECT":
                self.request.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                if tail:upstream.sendall(tail)
            else:
                path=address.path or "/"
                if address.query:path+="?"+address.query
                upstream.sendall(f"{method} {path} {version}\r\n".encode()+b"\r\n".join(headers)+b"\r\n\r\n"+tail)
            upstream.settimeout(None)
            while True:
                ready,_,_=select.select([self.request,upstream],[],[],5)
                if not ready:return
                for source in ready:
                    try:
                        part=source.recv(65536)
                        if not part:return
                        (upstream if source is self.request else self.request).sendall(part)
                    except OSError:return
