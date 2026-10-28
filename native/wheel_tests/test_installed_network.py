"""Public Context API tests; this process has no external network dependencies."""
import json
import os
from pathlib import Path
import time
import unittest

from ruyijs import Context

PEERS = json.loads(Path(__file__).with_name('peers.json').read_text())


class InstalledNetworkTests(unittest.TestCase):
    def context(self):
        previous = os.environ.get('RUYIJS_CA_BUNDLE')
        os.environ['RUYIJS_CA_BUNDLE'] = PEERS['ca']
        try: context = Context(timeout=10)
        finally:
            if previous is None: os.environ.pop('RUYIJS_CA_BUNDLE', None)
            else: os.environ['RUYIJS_CA_BUNDLE'] = previous
        self.addCleanup(context.close)
        return context

    def result(self, context):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            value = context.eval('result')
            if value is not None:
                self.assertNotIn('error', value)
                return value
            context.advance(5); time.sleep(.005)
        self.fail('Installed runtime network operation timed out')

    def test_http_redirect_cookie_script_and_compression(self):
        context = self.context()
        context.navigate(PEERS['http'] + '/redirect')
        self.assertEqual(context.eval('[document.title,networkValue]'), ['Native HTTP',42])
        self.assertIn('ruyi=1', context.eval('document.cookie'))
        context.eval("""globalThis.result=null;(async()=>{
            const data={};for(const path of ['chunked','gzip','deflate','brotli','zstd'])
              data[path]=await(await fetch('/'+path)).text();result={data};
        })().catch(e=>result={error:String(e)});undefined""")
        self.assertEqual(set(self.result(context)['data'].values()), {'native network 中文🦊'})

    def test_https_and_http2(self):
        context = self.context()
        context.navigate(PEERS['https'] + '/page')
        self.assertEqual(context.eval('document.title'), 'Native HTTP')
        context.navigate(PEERS['h2'] + '/context')
        self.assertEqual(context.eval("performance.getEntriesByType('navigation')[0].nextHopProtocol"), 'h2')

    def test_http3_navigation_and_fetch(self):
        context = self.context()
        context.navigate(PEERS['alternate'] + '/page')
        context.navigate(PEERS['alternate'] + '/h3')
        self.assertEqual(context.eval("[document.title,h3Value,performance.getEntriesByType('navigation')[0].nextHopProtocol]"),
                         ['Native HTTP3',42,'h3'])
        context.eval("globalThis.result=null;fetch('/h3').then(r=>r.text()).then(text=>result={text}).catch(e=>result={error:String(e)});undefined")
        self.assertIn('Native HTTP3', self.result(context)['text'])

    def test_webtransport_stream_datagram_and_tls_exporter(self):
        context = self.context()
        context.load_page('https://localhost/', '<title>Installed WebTransport</title>')
        context.set('quicUrl', PEERS['quic'] + '/echo')
        context.set('certificateHash', PEERS['certificate_hash'])
        context.eval("""globalThis.result=null;(async()=>{
            const transport=globalThis.transport=new WebTransport(quicUrl,{
              serverCertificateHashes:[{algorithm:'sha-256',value:new Uint8Array(certificateHash)}]});
            transport.closed.catch(()=>{});await transport.ready;
            const stream=await transport.createBidirectionalStream();
            const writer=stream.writable.getWriter();
            await writer.write(new Uint8Array([1,2,3]));await writer.close();
            const reader=stream.readable.getReader(),echo=await reader.read(),fin=await reader.read();
            const incoming=await transport.incomingUnidirectionalStreams.getReader().read();
            const remote=await incoming.value.getReader().read();
            const sender=transport.datagrams.writable.getWriter(),receiver=transport.datagrams.readable.getReader();
            await sender.write(new Uint8Array([7,8]));const datagram=await receiver.read();
            const key=await transport.exportKeyingMaterial(new TextEncoder().encode('test'),new TextEncoder().encode('context'));
            await sender.write(new TextEncoder().encode('export'));const remoteKey=await receiver.read();
            transport.close({closeCode:4,reason:'wheel'});const closed=await transport.closed;
            result={echo:Array.from(echo.value),fin:fin.done,remote:new TextDecoder().decode(remote.value),
              datagram:Array.from(datagram.value),keyMatches:String(key)===String(remoteKey.value),closed};
        })().catch(e=>result={error:String(e)});undefined""")
        self.assertEqual(self.result(context), {'echo':[1,2,3], 'fin':True, 'remote':'server uni',
                         'datagram':[7,8], 'keyMatches':True, 'closed':{'closeCode':4,'reason':'wheel'}})

    def test_webtransport_wrong_certificate_rejected(self):
        context = self.context()
        context.load_page('https://localhost/', '<title>Certificate rejection</title>')
        context.set('quicUrl', PEERS['quic'] + '/echo')
        context.eval("""globalThis.result=null;
            const transport=new WebTransport(quicUrl,{serverCertificateHashes:[{algorithm:'sha-256',value:new Uint8Array(32)}]});
            Promise.all([transport.ready.then(()=>false,e=>e.name),transport.closed.then(()=>false,e=>e.name)])
              .then(values=>result={values});undefined""")
        self.assertEqual(self.result(context)['values'], ['WebTransportError','WebTransportError'])
