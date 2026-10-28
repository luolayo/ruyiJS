"""Read-only public HTTPS check; separate from deterministic local regressions."""
import json
from pathlib import Path
import sys

from necko.adapters import HTTPAdapter
from requests import Request
from ruyijs_necko import RequestControl,open_response

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'python'))
from ruyijs import Context

url='https://example.com/'
adapter=HTTPAdapter()
try:
    with open_response(adapter,Request('GET',url).prepare(),RequestControl(20),timeout=(10,10),verify=True) as response:
        body=b''.join(response)
        report={'url':url,'status':response.status,'body_bytes':len(body),'version':response.version,'tls':response.tls}
finally:
    adapter.close()
with Context(timeout=25) as context:
    context.navigate(url)
    report['context']=context.eval("({title:document.title,url:location.href,protocol:performance.getEntriesByType('navigation')[0].nextHopProtocol})")
assert report['status']==200 and report['tls']['backend']=='NSS'
assert report['context']['title']=='Example Domain'
print(json.dumps(report))
