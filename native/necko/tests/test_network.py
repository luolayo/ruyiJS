import json
import os
from pathlib import Path
import subprocess
import shlex
import sys
import tempfile
import time
import unittest

from fixtures import Server,HttpHandler,H2Handler,certificates,PAYLOAD
from proxy_fixture import ProxyHandler
from necko.adapters import HTTPAdapter
from requests import Request
from ruyijs_necko import RequestControl,open_response

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/"python"))
from ruyijs import Context


class NetworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory=tempfile.TemporaryDirectory(prefix="ruyijs-network-")
        cls.ca,certs=certificates(cls.directory.name)
        cls.http=Server();cls.https=Server(certificate=certs[0]);cls.h2=Server(H2Handler,certs[0],"h2")
        cls.wrong=Server(certificate=certs[1])
        cls.proxy=Server(ProxyHandler)

    @classmethod
    def tearDownClass(cls):
        for server in (cls.http,cls.https,cls.h2,cls.wrong,cls.proxy):server.close()
        cls.directory.cleanup()

    def request(self,url,*,verify=True,timeout=3,method="GET",body=None,adapter=None,proxies=None):
        owned=adapter is None;adapter=adapter or HTTPAdapter()
        try:
            with open_response(adapter,Request(method,url,data=body).prepare(),RequestControl(timeout,max_attempts=1),
                               timeout=(timeout,timeout),verify=verify,proxies=proxies or {}) as response:
                data=b"".join(response)
                return response.status,data,response.version,response.tls
        finally:
            if owned:adapter.close()

    def test_http_post_and_connection_reuse(self):
        adapter=HTTPAdapter()
        try:
            for index in range(3):
                status,body,version,_=self.request(self.http.url+"/echo",method="POST",body=f"data-{index}",adapter=adapter)
                self.assertEqual((status,version),(200,11))
                self.assertEqual(json.loads(body)["body"],f"data-{index}")
        finally:adapter.close()

    def test_chunked_and_compressed_bodies(self):
        for path in ("/chunked","/gzip","/deflate","/brotli","/zstd"):
            with self.subTest(path=path):self.assertEqual(self.request(self.http.url+path)[1],PAYLOAD)

    def test_invalid_framing_is_rejected(self):
        for path in ("/bad-length","/bad-chunk","/bad-header"):
            with self.subTest(path=path),self.assertRaises(Exception):self.request(self.http.url+path)

    def test_timeout_is_bounded(self):
        start=time.monotonic()
        with self.assertRaises(Exception):self.request(self.http.url+"/slow",timeout=.15)
        self.assertLess(time.monotonic()-start,1)

    def test_https_uses_nss_and_verifies_chain(self):
        status,_,version,tls=self.request(self.https.url+"/echo",verify=str(self.ca))
        self.assertEqual((status,version),(200,11))
        self.assertEqual(tls["backend"],"NSS");self.assertEqual(tls["nss"],"3.130")
        with self.assertRaises(Exception):self.request(self.https.url+"/echo")
        with self.assertRaises(Exception):self.request(self.wrong.url+"/echo",verify=str(self.ca))

    def test_http2_alpn(self):
        status,body,version,tls=self.request(self.h2.url+"/h2",verify=str(self.ca))
        self.assertEqual((status,version,tls["alpn"]),(200,20,"h2"))
        self.assertEqual(json.loads(body),{"path":"/h2","alpn":"h2"})

    def test_http_proxy_and_https_connect(self):
        proxy={"http":self.proxy.url,"https":self.proxy.url}
        self.assertEqual(self.request(self.http.url+"/echo",proxies=proxy)[0],200)
        status,_,version,tls=self.request(self.https.url+"/echo",verify=str(self.ca),proxies=proxy)
        self.assertEqual((status,version,tls["backend"]),(200,11,"NSS"))

    def test_context_navigation_redirect_cookie_and_fetch(self):
        with Context(timeout=10) as context:
            context.navigate(self.http.url+"/redirect")
            self.assertEqual(context.eval("[document.title,networkValue]"),["Native HTTP",42])
            self.assertIn("ruyi=1",context.eval("document.cookie"))
            context.eval("globalThis.result=null;fetch('/echo').then(r=>r.json()).then(x=>result=x).catch(e=>result={error:String(e)});undefined")
            for _ in range(100):
                result=context.eval("result")
                if result is not None:break
                context.advance(5);time.sleep(.01)
            self.assertIn("ruyi=1",result["cookie"])

    def test_context_https_and_helper_cleanup(self):
        previous=os.environ.get("RUYIJS_CA_BUNDLE")
        os.environ["RUYIJS_CA_BUNDLE"]=str(self.ca)
        try:context=Context(timeout=10)
        finally:
            if previous is None:os.environ.pop("RUYIJS_CA_BUNDLE",None)
            else:os.environ["RUYIJS_CA_BUNDLE"]=previous
        with context:
            context.navigate(self.h2.url+"/context")
            self.assertEqual(context.eval("performance.getEntriesByType('navigation')[0].nextHopProtocol"),"h2")
            children=[int(p) for p in subprocess.check_output(["pgrep","-P",str(context._process.pid)],text=True).split()]
        deadline=time.monotonic()+3
        while children and time.monotonic()<deadline:
            alive=[]
            for pid in children:
                try:os.kill(pid,0);alive.append(pid)
                except ProcessLookupError:pass
            children=alive;time.sleep(.02)
        self.assertEqual(children,[])

    def test_cancel_during_helper_startup_leaves_no_process(self):
        wrapper=Path(self.directory.name)/"delayed-python"
        pids=Path(self.directory.name)/"helper-pids"
        wrapper.write_text("#!/bin/sh\nprintf '%s\\n' $$ >> "+shlex.quote(str(pids))+"\nsleep 1\nexec "+shlex.quote(sys.executable)+" \"$@\"\n")
        wrapper.chmod(0o700)
        previous=os.environ.get("RUYIJS_NECKO_PYTHON")
        os.environ["RUYIJS_NECKO_PYTHON"]=str(wrapper)
        try:context=Context(timeout=5)
        finally:
            if previous is None:os.environ.pop("RUYIJS_NECKO_PYTHON",None)
            else:os.environ["RUYIJS_NECKO_PYTHON"]=previous
        ready=time.monotonic()+2
        while not pids.exists() and time.monotonic()<ready:time.sleep(.02)
        self.assertTrue(pids.exists(),"delayed helper did not start")
        context.timeout=.15
        try:
            with self.assertRaises(TimeoutError):context.navigate(self.http.url+"/very-slow")
        finally:context.close()
        time.sleep(.1)
        children=[int(p) for p in pids.read_text().split()]
        deadline=time.monotonic()+3
        while children and time.monotonic()<deadline:
            alive=[]
            for pid in children:
                try:os.kill(pid,0);alive.append(pid)
                except ProcessLookupError:pass
            children=alive;time.sleep(.02)
        for pid in children:os.kill(pid,9)
        self.assertEqual(children,[])


if __name__=="__main__":unittest.main()
