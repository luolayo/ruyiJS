"""Integration servers outside the wheel client's filesystem sandbox."""
import argparse
import json
from pathlib import Path
import sys
import tempfile

from fixtures import Server, HttpHandler, H2Handler, certificates
from quic_fixture import QuicPeer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--peer', type=Path)
    parser.add_argument('--native', type=Path)
    parser.add_argument('--nss-tools', type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='ruyijs-wheel-peers-', dir='/tmp') as directory:
        ca, certs = certificates(directory, elliptic=True)
        peer = QuicPeer(Path(directory) / 'quic', certs[0], binary=args.peer,
                        native=args.native, nss_tools=args.nss_tools)
        class Alternate(HttpHandler):
            def end_headers(self):
                self.send_header('Alt-Svc', f'h3=":{peer.port}"; ma=60')
                super().end_headers()
        servers = [Server(), Server(certificate=certs[0]), Server(H2Handler, certs[0], 'h2'), Server(Alternate, certs[0])]
        try:
            print(json.dumps({'http':servers[0].url, 'https':servers[1].url, 'h2':servers[2].url,
                              'alternate':servers[3].url, 'quic':peer.url,
                              'ca':str(ca), 'certificate_hash':list(peer.hash)}), flush=True)
            sys.stdin.readline()
        finally:
            for server in servers: server.close()
            peer.close()


if __name__ == '__main__': main()
