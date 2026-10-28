"""Force a public HTTP/3 request; failure must never silently pass via TCP."""
import argparse
import json
from pathlib import Path
import socket
import time

from necko._http3 import Connection, Exchange
from necko._nss import Context
from urllib3._collections import HTTPHeaderDict
from urllib.parse import urlsplit
import necko


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url', nargs='?', default='https://www.cloudflare.com/')
    parser.add_argument('--address', help='Explicit peer IP; TLS still authenticates the URL hostname')
    args = parser.parse_args()
    target = urlsplit(args.url)
    report = {'url':args.url, 'passed':False, 'tcp_fallback':False, 'explicit_address':args.address}
    connection = exchange = None
    start = time.monotonic()
    try:
        if target.scheme != 'https' or not target.hostname:
            raise ValueError('Expected an HTTPS URL')
        addresses = socket.getaddrinfo(args.address or target.hostname, target.port or 443, type=socket.SOCK_DGRAM)
        report['peer'] = addresses[0][4][0]
        connection = Connection(target.hostname, target.port or 443, Context(True, None),
            str(Path(necko.__file__).parent / 'libnecko_core.dylib'), 10, resolved=addresses[0])
        exchange = Exchange(connection, 'GET', args.url,
            HTTPHeaderDict({'Host':target.netloc, 'User-Agent':'ruyijs-macos-network-test'}), False, 10)
        exchange.receive()
        total = 0
        while chunk := exchange.read(65536): total += len(chunk)
        report.update(status=exchange.status, body_bytes=total, protocol='h3', tls=connection.info)
        if exchange.status != 200 or total == 0 or connection.info['alpn'] != 'h3':
            raise AssertionError('Expected a nonempty HTTP 200 response over h3')
        report['passed'] = True
    except Exception as error:
        report.update(error=str(error), error_type=type(error).__name__)
    finally:
        if exchange is not None: exchange.close()
        if connection is not None: connection.close()
    report['elapsed_seconds'] = round(time.monotonic() - start, 3)
    print(json.dumps(report))
    return 0 if report['passed'] else 1


if __name__ == '__main__': raise SystemExit(main())
