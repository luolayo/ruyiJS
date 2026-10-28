"""Local HTTP, TLS and h2 peers with a disposable test certificate authority."""
import datetime
import gzip
import ipaddress
import json
from pathlib import Path
import socketserver
import ssl
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import brotli
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, ec
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
import h2.config
import h2.connection
import h2.events
import zstandard

PAYLOAD = "native network 中文🦊".encode()


def certificates(directory, *, elliptic=False):
    now = datetime.datetime.now(datetime.timezone.utc)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ruyiJS temporary test CA")])
    ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(days=1))
          .not_valid_after(now+datetime.timedelta(days=1)).add_extension(x509.BasicConstraints(ca=True,path_length=1),True)
          .add_extension(x509.KeyUsage(False,False,False,False,False,True,True,False,False),True)
          .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()),False).sign(key,hashes.SHA256()))
    root = Path(directory)/"ca.pem"
    root.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    paths = []
    for label, hosts in (("valid",[x509.DNSName("localhost"),x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
                         ("wrong-host",[x509.DNSName("wrong.invalid")])):
        private = ec.generate_private_key(ec.SECP256R1()) if elliptic else rsa.generate_private_key(public_exponent=65537,key_size=2048)
        leaf = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,"localhost")]))
                .issuer_name(name).public_key(private.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now-datetime.timedelta(hours=1)).not_valid_after(now+datetime.timedelta(hours=1))
                .add_extension(x509.BasicConstraints(ca=False,path_length=None),True)
                .add_extension(x509.SubjectAlternativeName(hosts),False)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),False)
                .add_extension(x509.KeyUsage(True,False,True,False,False,False,False,False,False),True)
                .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()),False)
                .add_extension(x509.SubjectKeyIdentifier.from_public_key(private.public_key()),False)
                .sign(key,hashes.SHA256()))
        cert = Path(directory)/(label+".pem"); secret = Path(directory)/(label+".key")
        cert.write_bytes(leaf.public_bytes(serialization.Encoding.PEM)+ca.public_bytes(serialization.Encoding.PEM))
        secret.write_bytes(private.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        secret.chmod(0o600);paths.append((cert,secret))
    return root, paths


class HttpHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):
        self.do_GET()

    def do_GET(self):
        body = self.rfile.read(int(self.headers.get("Content-Length",0)))
        if self.path == "/slow":
            time.sleep(1)
        if self.path == "/very-slow":
            time.sleep(5)
        if self.path == "/bad-length":
            self.wfile.write(b"HTTP/1.1 200 OK\r\nContent-Length: 3\r\nContent-Length: 4\r\nConnection: close\r\n\r\nabcd")
            self.close_connection=True;return
        if self.path == "/bad-header":
            self.wfile.write(b"HTTP/1.1 200 OK\r\nContent-Length : 4\r\nConnection: close\r\n\r\nabcd")
            self.close_connection=True;return
        if self.path in ("/chunked","/bad-chunk"):
            self.send_response(200);self.send_header("Transfer-Encoding","chunked");self.end_headers()
            if self.path == "/bad-chunk":
                self.wfile.write(b"bad-size\r\n");self.close_connection=True;return
            for part in (PAYLOAD[:4],PAYLOAD[4:]):
                self.wfile.write(f"{len(part):x}\r\n".encode()+part+b"\r\n")
            self.wfile.write(b"0\r\nX-Trailer: yes\r\n\r\n");return
        headers=[];status=200
        if self.path == "/page":
            payload=b"<!doctype html><title>Native HTTP</title><script>window.networkValue=42</script>"
            headers.append(("Content-Type","text/html"))
        elif self.path == "/redirect":
            payload=b"";status=302;headers=[("Location","/page"),("Set-Cookie","ruyi=1; Path=/")]
        elif self.path in ("/gzip","/deflate","/brotli","/zstd"):
            encoding={"/gzip":"gzip","/deflate":"deflate","/brotli":"br","/zstd":"zstd"}[self.path]
            payload=gzip.compress(PAYLOAD) if encoding=="gzip" else zlib.compress(PAYLOAD) if encoding=="deflate" else brotli.compress(PAYLOAD) if encoding=="br" else zstandard.ZstdCompressor().compress(PAYLOAD)
            headers.append(("Content-Encoding",encoding))
        else:
            payload=json.dumps({"path":self.path,"body":body.decode(),"cookie":self.headers.get("Cookie","")}).encode()
            headers.append(("Content-Type","application/json"))
        self.send_response(status)
        for key,value in headers:self.send_header(key,value)
        self.send_header("Content-Length",str(len(payload)));self.end_headers()
        try:self.wfile.write(payload)
        except (BrokenPipeError,ConnectionResetError):pass

    def log_message(self,*_):pass


class H2Handler(socketserver.BaseRequestHandler):
    def handle(self):
        connection=h2.connection.H2Connection(h2.config.H2Configuration(client_side=False,header_encoding="utf-8"))
        connection.initiate_connection();self.request.sendall(connection.data_to_send())
        requests={}
        while True:
            try:data=self.request.recv(65536)
            except (OSError,ssl.SSLError):return
            if not data:return
            for event in connection.receive_data(data):
                if isinstance(event,h2.events.RequestReceived):requests[event.stream_id]=dict(event.headers)
                if isinstance(event,h2.events.DataReceived):connection.acknowledge_received_data(event.flow_controlled_length,event.stream_id)
                if isinstance(event,h2.events.StreamEnded):
                    payload=json.dumps({"path":requests[event.stream_id][":path"],"alpn":self.request.selected_alpn_protocol()}).encode()
                    connection.send_headers(event.stream_id,[(":status","200"),("content-type","application/json"),("content-length",str(len(payload)))])
                    connection.send_data(event.stream_id,payload,end_stream=True)
            try:self.request.sendall(connection.data_to_send())
            except OSError:return


class Server:
    def __init__(self, handler=HttpHandler, certificate=None, alpn="http/1.1"):
        server_type=ThreadingHTTPServer if handler is HttpHandler else socketserver.ThreadingTCPServer
        self.server=server_type(("127.0.0.1",0),handler)
        self.server.daemon_threads=True
        if certificate:
            context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version=ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(*map(str,certificate));context.set_alpn_protocols([alpn])
            self.server.socket=context.wrap_socket(self.server.socket,server_side=True)
        self.url=("https" if certificate else "http")+f"://127.0.0.1:{self.server.server_address[1]}"
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()

    def close(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
