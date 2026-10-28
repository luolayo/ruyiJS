import base64
import subprocess
import os
from pathlib import Path
import socket
import ssl
import sys
import tempfile
import time
import unittest

from fixtures import certificates, HttpHandler, Server
from quic_fixture import QuicPeer, ROOT, NATIVE
from necko._http3 import Connection, Exchange
from necko._nss import Context as Trust
from ruyijs_necko.webtransport_session import Session, StreamError
from urllib3._collections import HTTPHeaderDict

sys.path.insert(0, str(ROOT / 'python'))
from ruyijs import Context


def encoded(data):
    return base64.b64encode(data).decode()


class QuicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix='ruyijs-quic-')
        cls.ca, cls.certs = certificates(cls.directory.name, elliptic=True)
        cls.peer = QuicPeer(Path(cls.directory.name) / 'peer', cls.certs[0])

    @classmethod
    def tearDownClass(cls):
        cls.peer.close()
        cls.directory.cleanup()

    def connection(self, host='127.0.0.1', verify=None, timeout=3):
        return Connection(host, self.peer.port, Trust(str(self.ca) if verify is None else verify, None),
            str(NATIVE / 'libnecko_core.dylib'), timeout, endpoint=('127.0.0.1', self.peer.port))

    def session(self, path='/echo', **kwargs):
        return Session(self.peer.url + path, 'https://localhost', hashes=[('sha-256', self.peer.hash)], timeout=3, **kwargs)

    def poll_until(self, session, predicate):
        deadline = time.monotonic() + 3
        events = []
        while time.monotonic() < deadline:
            events.extend(session.poll())
            if predicate(events): return events
            time.sleep(.005)
        self.fail('Missing WebTransport events: ' + repr(events))

    def read_all(self, session, stream):
        result = b''
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            value = session.read(stream)
            result += base64.b64decode(value['data'])
            if value['fin']: return result
            time.sleep(.005)
        self.fail('WebTransport stream FIN timeout')

    def test_http3_get_post_and_multiplex(self):
        connection = self.connection()
        try:
            self.assertEqual(connection.info['alpn'], 'h3')
            exchanges = [Exchange(connection, 'GET', self.peer.url + '/h3', HTTPHeaderDict({'Host': '127.0.0.1'}), False, 3) for _ in range(3)]
            for exchange in exchanges:
                exchange.receive()
                self.assertEqual(exchange.status, 200)
                body = b''
                while chunk := exchange.read(65536): body += chunk
                self.assertIn(b'Native HTTP3', body)
                exchange.close()
            exchange = Exchange(connection, 'POST', self.peer.url + '/echo', HTTPHeaderDict({'Host': '127.0.0.1'}), True, 3)
            data = b'QUIC upload ' * 10000
            exchange.write(data); exchange.receive()
            result = b''
            while chunk := exchange.read(65536): result += chunk
            self.assertEqual(result, data)
            exchange.close()
        finally: connection.close()
        self.assertFalse(connection._thread.is_alive())

    def test_http3_rejects_wrong_ca_and_hostname(self):
        with self.assertRaises(ssl.SSLCertVerificationError): self.connection(verify=True)
        with self.assertRaises(ssl.SSLCertVerificationError): self.connection(host='wrong.invalid')

    def test_webtransport_bidirectional_unidirectional_and_datagrams(self):
        session = self.session(protocols=['echo'])
        try:
            self.assertEqual(session.info['protocol'], 'echo')
            self.assertGreater(session.info['maxDatagramSize'], 100)
            events = self.poll_until(session, lambda events: len([e for e in events if e['type'] == 'wt_stream']) == 2)
            for event in events:
                if event['type'] == 'wt_stream':
                    self.assertEqual(self.read_all(session, event['stream']), b'server bidi' if event['bidirectional'] else b'server uni')
            stream = session.stream(True)
            payload = b'WebTransport payload ' * 10000
            for offset in range(0, len(payload), 65536):
                part = payload[offset:offset+65536]
                while part:
                    written = session.write(stream, encoded(part)); part = part[written:]
            session.finish(stream)
            self.assertEqual(self.read_all(session, stream), payload)
            uni = session.stream(False)
            self.assertEqual(session.write(uni, encoded(b'outgoing')), 8)
            session.finish(uni)
            session.command('datagram', session=session.session, data=encoded(b'hello datagram'))
            values = self.poll_until(session, lambda es: len([e for e in es if e['type'] == 'wt_datagram']) >= 2)
            received = [base64.b64decode(e['data']) for e in values if e['type'] == 'wt_datagram']
            self.assertIn(b'uni:outgoing', received); self.assertIn(b'hello datagram', received)
            info = session.command('info', session=session.session)
            self.assertGreater(info['bytesReceived'], len(payload))
        finally: session.close()
        self.assertFalse(session.connection._thread.is_alive())

    def test_webtransport_export_groups_and_peer_close(self):
        session = self.session()
        try:
            group = session.command('group', session=session.session)['group']
            stream = session.stream(True, group=group, order=-2)
            session.command('order', stream=stream, order=8)
            session.command('set_group', session=session.session, stream=stream, group=None)
            stats = session.command('stream_stats', stream=stream, sending=True)
            self.assertEqual(stats['bytesWritten'], 0)
            exported = session.command('export', session=session.session, label=encoded(b'test'), context=encoded(b'context'))['data']
            session.command('datagram', session=session.session, data=encoded(b'export'))
            events = self.poll_until(session, lambda es: any(e['type'] == 'wt_datagram' for e in es))
            self.assertEqual(next(e['data'] for e in events if e['type'] == 'wt_datagram'), exported)
            session.command('datagram', session=session.session, data=encoded(b'close'))
            events = self.poll_until(session, lambda es: any(e['type'] == 'wt_closed' for e in es))
            closed = next(e for e in events if e['type'] == 'wt_closed')
            self.assertEqual((closed['clean'], closed['code'], closed['reason']), (True, 42, 'peer closed'))
        finally: session.close()

    def test_webtransport_bad_hash_and_rejected_session(self):
        with self.assertRaises(ssl.SSLCertVerificationError):
            Session(self.peer.url + '/echo', 'https://localhost', hashes=[('sha-256', bytes(32))], timeout=2)
        with self.assertRaisesRegex(Exception, '403'): self.session('/reject')

    def test_webtransport_stream_error(self):
        session = self.session()
        try:
            stream = session.stream(True)
            session.write(stream, encoded(b'reset'))
            events = self.poll_until(session, lambda es: any(e['type'] == 'wt_reset' for e in es))
            self.assertEqual(next(e['code'] for e in events if e['type'] == 'wt_reset'), 7)
            with self.assertRaises(StreamError) as raised: session.read(stream)
            self.assertEqual(raised.exception.code, 7)
        finally: session.close()

    def context_result(self, context):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            result = context.eval('result')
            if result is not None:
                self.assertNotIn('error', result)
                return result
            context.advance(5); time.sleep(.005)
        self.fail('Context WebTransport timed out')

    def assert_children_exit(self, children):
        deadline = time.monotonic() + 3
        while children and time.monotonic() < deadline:
            alive = []
            for pid in children:
                try: os.kill(pid, 0); alive.append(pid)
                except ProcessLookupError: pass
            children = alive; time.sleep(.01)
        self.assertEqual(children, [])

    def test_context_webtransport_streams_datagram_export_and_cleanup(self):
        with Context(timeout=10) as context:
            context.load_page('https://localhost/', '<title>WebTransport test</title>')
            context.set('quicUrl', self.peer.url + '/echo')
            context.set('certificateHash', list(self.peer.hash))
            context.eval("""
                globalThis.result=null;
                (async()=>{
                  const transport=globalThis.transport=new WebTransport(quicUrl,{
                    serverCertificateHashes:[{algorithm:'sha-256',value:new Uint8Array(certificateHash)}],protocols:['echo']});
                  transport.closed.catch(()=>{});
                  await transport.ready;
                  const incoming=await transport.incomingUnidirectionalStreams.getReader().read();
                  const remote=await incoming.value.getReader().read();
                  const stream=await transport.createBidirectionalStream();
                  const writer=stream.writable.getWriter();
                  await writer.write(new Uint8Array([1,2,3,4])); await writer.close();
                  const reader=stream.readable.getReader();
                  const echo=await reader.read(); const end=await reader.read();
                  const datagrams=transport.datagrams.readable.getReader();
                  const sender=transport.datagrams.writable.getWriter();
                  await sender.write(new Uint8Array([9,8,7]));
                  const datagram=await datagrams.read();
                  const key=await transport.exportKeyingMaterial(new TextEncoder().encode('test'),new TextEncoder().encode('context'));
                  await sender.write(new TextEncoder().encode('export'));
                  const remoteKey=await datagrams.read();
                  const stats=await transport.getStats();
                  transport.close({closeCode:23,reason:'complete'});
                  const closed=await transport.closed;
                  result={echo:Array.from(echo.value),fin:end.done,datagram:Array.from(datagram.value),
                    remote:new TextDecoder().decode(remote.value),keyMatches:String(key)===String(remoteKey.value),
                    keyLength:key.length,received:stats.bytesReceived,closed};
                })().catch(e=>{result={error:String(e),stack:e.stack}});undefined
            """)
            result = self.context_result(context)
            self.assertEqual(result['echo'], [1,2,3,4]); self.assertTrue(result['fin'])
            self.assertEqual(result['datagram'], [9,8,7]); self.assertEqual(result['remote'], 'server uni')
            self.assertTrue(result['keyMatches']); self.assertEqual(result['keyLength'], 32)
            self.assertGreater(result['received'], 0)
            self.assertEqual(result['closed'], {'closeCode':23, 'reason':'complete'})
            children = [int(p) for p in subprocess.check_output(['pgrep','-P',str(context._process.pid)],text=True).split()]
        self.assert_children_exit(children)

    def test_context_http3_alt_svc_navigation_and_fetch(self):
        port = self.peer.port
        class Alternate(HttpHandler):
            def end_headers(self):
                self.send_header('Alt-Svc', f'h3=":{port}"; ma=60')
                super().end_headers()
        https = Server(Alternate, self.certs[0])
        previous = os.environ.get('RUYIJS_CA_BUNDLE')
        os.environ['RUYIJS_CA_BUNDLE'] = str(self.ca)
        try: context = Context(timeout=10)
        finally:
            if previous is None: os.environ.pop('RUYIJS_CA_BUNDLE',None)
            else: os.environ['RUYIJS_CA_BUNDLE'] = previous
        try:
            with context:
                context.navigate(https.url + '/page')
                context.navigate(https.url + '/h3')
                self.assertEqual(context.eval("[document.title,h3Value,performance.getEntriesByType('navigation')[0].nextHopProtocol]"), ['Native HTTP3',42,'h3'])
                context.eval("globalThis.result=null;fetch('/h3').then(r=>r.text()).then(text=>result={text}).catch(e=>result={error:String(e)});undefined")
                self.assertIn('Native HTTP3', self.context_result(context)['text'])
        finally: https.close()

    def test_context_bad_hash_rejects_ready_and_closed(self):
        with Context(timeout=10) as context:
            context.load_page('https://localhost/', '<title>WebTransport rejection</title>')
            context.set('quicUrl', self.peer.url + '/echo')
            context.eval("""
                globalThis.result=null;
                const rejected=new WebTransport(quicUrl,{serverCertificateHashes:[{algorithm:'sha-256',value:new Uint8Array(32)}]});
                Promise.all([rejected.ready.then(()=>false,e=>e.name),rejected.closed.then(()=>false,e=>e.name)])
                  .then(values=>result={values});undefined
            """)
            self.assertEqual(self.context_result(context)['values'], ['WebTransportError','WebTransportError'])

    def test_context_cancel_pending_webtransport_leaves_no_helper(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as blackhole:
            blackhole.bind(('127.0.0.1', 0))
            with Context(timeout=10) as context:
                context.load_page('https://localhost/', '<title>Cancel handshake</title>')
                context.set('quicUrl', f'https://127.0.0.1:{blackhole.getsockname()[1]}/echo')
                context.eval("globalThis.transport=new WebTransport(quicUrl);transport.ready.catch(()=>{});transport.closed.catch(()=>{});undefined")
                # Wait for an actual QUIC Initial, so this tests an active helper.
                blackhole.settimeout(3)
                self.assertGreater(len(blackhole.recv(65536)), 0)
                children = [int(p) for p in subprocess.check_output(['pgrep','-P',str(context._process.pid)],text=True).split()]
                self.assertTrue(children)
            self.assert_children_exit(children)

    def test_udp_timeout_and_cleanup(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as blackhole:
            blackhole.bind(('127.0.0.1', 0))
            start = time.monotonic()
            with self.assertRaises(TimeoutError):
                Connection('localhost', blackhole.getsockname()[1], Trust(str(self.ca), None),
                    str(NATIVE / 'libnecko_core.dylib'), .2, endpoint=blackhole.getsockname())
            self.assertLess(time.monotonic() - start, 1.5)


if __name__ == '__main__': unittest.main()
