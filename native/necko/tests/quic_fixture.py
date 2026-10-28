"""Real loopback UDP peer using the pinned Neqo build and ephemeral identities."""
import hashlib
import os
from pathlib import Path
import select
import subprocess

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12

ROOT = Path(__file__).resolve().parents[3]
NATIVE = ROOT / 'vendor/necko-derived/lib/python3.13/site-packages/necko'


class QuicPeer:
    def __init__(self, directory, certificate, *, binary=None, native=None, nss_tools=None):
        directory = Path(directory)
        directory.mkdir()
        self.process = None
        self.log = (directory / 'peer.log').open('w+')
        cert, key = certificate
        chain = x509.load_pem_x509_certificates(cert.read_bytes())
        self.hash = hashlib.sha256(chain[0].public_bytes(serialization.Encoding.DER)).digest()
        private = serialization.load_pem_private_key(key.read_bytes(), None)
        identity = directory / 'identity.p12'
        identity.write_bytes(pkcs12.serialize_key_and_certificates(b'peer', private, chain[0], chain[1:],
            serialization.BestAvailableEncryption(b'local-test')))
        identity.chmod(0o600)
        binary = binary or ROOT / 'build/macos-arm64/quic/target/release/examples/peer'
        native = native or NATIVE
        nss_tools = Path(nss_tools or '/opt/homebrew/opt/nss/bin')
        try:
            for command in [
                [nss_tools / 'certutil', '-N', '-d', str(directory), '--empty-password'],
                [nss_tools / 'pk12util', '-i', str(identity), '-d', str(directory), '-W', 'local-test', '-K', ''],
            ]:
                subprocess.run(command, check=True, stdout=self.log, stderr=subprocess.STDOUT, timeout=15)
            # NSS tools only prepare the test database. The running peer and
            # product both load the hash-pinned Firefox libraries, not Homebrew NSS.
            self.process = subprocess.Popen([binary, str(directory)],
                stdout=subprocess.PIPE, stderr=self.log, text=True,
                env=dict(os.environ, DYLD_LIBRARY_PATH=str(native)))
            if not select.select([self.process.stdout], [], [], 10)[0]:
                raise TimeoutError('Neqo test peer did not start')
            line = self.process.stdout.readline().strip()
            if not line.isdigit():
                self.log.flush()
                raise RuntimeError((directory / 'peer.log').read_text())
            self.port = int(line)
            self.url = f'https://127.0.0.1:{self.port}'
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.process is not None:
            self.process.terminate()
            try: self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill(); self.process.wait(timeout=3)
            self.process.stdout.close()
        self.log.close()
