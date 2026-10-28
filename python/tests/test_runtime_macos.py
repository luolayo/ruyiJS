"""End-to-end checks of the complete product, never a transport test peer."""
import os
import subprocess
import time
from ruyijs import Context, JSError
from runtime_support import MacRuntimeCase

class MacRuntimeTests(MacRuntimeCase):
    def test_eval_values_state_and_process_isolation(self):
        self.assertEqual(self.context.eval("1 + 2"), 3)
        self.context.set("input", {"answer": 21, "text": "中文🦊"})
        self.assertEqual(self.context.eval("({answer:input.answer*2,text:input.text,big:12345678901234567890n})"),
                         {"answer": 42, "text": "中文🦊", "big": 12345678901234567890})
        with Context(timeout=10) as other:
            self.assertEqual(other.eval("typeof input"), "undefined")
            self.assertNotEqual(other._process.pid, self.context._process.pid)


    def test_dom_and_python_callback(self):
        self.context.expose(lambda a, b: a + b, "pythonAdd")
        self.assertEqual(self.context.eval("pythonAdd(19,23)"), 42)
        self.assertEqual(self.context.eval('''(() => {
            const node=document.createElement('div'); node.id='mac'; node.textContent='native DOM';
            document.body.appendChild(node);
            return [globalThis===window,document.querySelector('#mac').textContent,node.tagName];
        })()'''), [True, "native DOM", "DIV"])


    def test_native_function_and_exception(self):
        self.context.native("twice", "value => value * 2")
        self.assertEqual(self.context.eval("twice(21)"), 42)
        self.assertIn("[native code]", self.context.eval("twice.toString()"))
        self.context.native("Point", "function Point(x) { this.x=x; }", constructor=True)
        self.assertEqual(self.context.eval("new Point(7).x"), 7)
        with self.assertRaises(JSError) as error:
            self.context.eval("throw new TypeError('mac failure')", filename="mac-smoke.js")
        self.assertEqual(error.exception.name, "TypeError")
        self.assertIn("mac failure", error.exception.message)
        self.assertEqual(self.context.eval("6*7"), 42)


    def test_urlpattern_uses_spidermonkey_regexp(self):
        self.assertEqual(self.context.eval('''new URLPattern({pathname:'/users/:id'}).
            exec('https://example.test/users/42').pathname.groups.id'''), "42")
        self.assertEqual(self.context.eval(r'''(() => {
            const p=new URLPattern({pathname:'/items/:id(\\d+)'});
            return [p.test('https://example.test/items/123'),p.test('https://example.test/items/abc'),p.hasRegExpGroups];
        })()'''), [True, False, True])


    def test_microtasks_and_timers(self):
        self.context.configure_clock("logical", epoch_ms=0)
        self.context.eval("globalThis.counter=0;Promise.resolve().then(()=>counter=1);setTimeout(()=>counter=7,20);undefined")
        self.assertEqual(self.context.eval("counter"), 1)
        self.context.advance(25)
        self.assertEqual(self.context.eval("counter"), 7)


    def test_infinite_script_timeout_disposes_native_process(self):
        context = Context(timeout=0.5)
        self.addCleanup(context.close)
        with self.assertRaises(TimeoutError):
            context.eval("while (true) {}")
        self.assertTrue(context.closed)
        self.assertIsNotNone(context._process.poll())


    def test_worker_and_offline_fetch(self):
        self.context.put_resource("https://example.test/data", "native resource")
        self.context.eval('''globalThis.result=null;fetch('https://example.test/data').then(r=>r.text()).then(v=>result=v)
            .catch(e=>result={error:String(e)});undefined''')
        self.assertEqual(self.await_value(), "native resource")
        self.context.eval('''globalThis.result=null;globalThis.worker=new Worker(URL.createObjectURL(
            new Blob(['onmessage=e=>postMessage(e.data*2)'],{type:'application/javascript'})));
            worker.onmessage=e=>result=e.data;worker.onerror=e=>result={error:e.message};worker.postMessage(21);undefined''')
        self.assertEqual(self.await_value(), 42)
        self.context.eval("worker.terminate();undefined")


    def test_busy_worker_exits_when_its_parent_is_killed(self):
        self.context.eval('''globalThis.result=null;globalThis.worker=new Worker(URL.createObjectURL(
            new Blob(["postMessage('ready');while(true){}"],{type:'application/javascript'})));
            worker.onmessage=e=>result=e.data;undefined''')
        self.assertEqual(self.await_value(), "ready")
        children = [int(p) for p in subprocess.check_output(["pgrep", "-P", str(self.context._process.pid)], text=True).split()]
        self.assertTrue(children)
        self.context._dispose()
        deadline = time.monotonic() + 3
        while children and time.monotonic() < deadline:
            alive = []
            for pid in children:
                try:
                    os.kill(pid, 0)
                    alive.append(pid)
                except ProcessLookupError:
                    pass
            children = alive
            time.sleep(0.02)
        self.assertEqual(children, [])
