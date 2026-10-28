"""Exercise native graphics, image and cryptography adapters through JavaScript."""
import struct
import zlib
from runtime_support import MacRuntimeCase

class NativeBackendTests(MacRuntimeCase):
    def test_canvas_fonts_and_image_decode(self):
        self.assertTrue(self.context.eval('''(() => {
            const c=document.createElement('canvas');c.width=80;c.height=30;
            const x=c.getContext('2d');x.font='16px serif';
            const measured=x.measureText('Mac').width;x.fillText('Mac',1,20);
            return measured>0 && x.getImageData(0,0,80,30).data.some(v=>v>0);
        })()'''))
        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        pixels = bytes([255,0,0,255, 0,255,0,255, 0,0,255,255, 255,255,255,255])
        png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB",2,2,8,6,0,0,0))
        png += chunk(b"IDAT", zlib.compress(b"\0"+pixels[:8]+b"\0"+pixels[8:])) + chunk(b"IEND", b"")
        url = self.context.eval("location.origin") + "/probe.png"
        self.context.put_resource(url, png, headers=[["Content-Type", "image/png"]])
        self.context.set("imageUrl", url)
        self.context.eval('''globalThis.result=null;globalThis.image=new Image();image.onload=()=>{
            createImageBitmap(image).then(bitmap=>{
                const c=document.createElement('canvas');c.width=2;c.height=2;
                const x=c.getContext('2d');x.drawImage(bitmap,0,0);
                const bitmapPixels=Array.from(x.getImageData(0,0,2,2).data);
                x.clearRect(0,0,2,2);x.drawImage(image,0,0);
                result={bitmap:bitmapPixels,direct:Array.from(x.getImageData(0,0,2,2).data)};
            }).catch(e=>result={error:String(e)});
        };image.onerror=()=>result={error:'image load failed'};image.src=imageUrl;undefined''')
        self.assertEqual(self.await_value(), {"bitmap":list(pixels),"direct":list(pixels)})


    def test_compression_stream_backends(self):
        self.context.eval('''globalThis.result=null;(async()=>{
            async function convert(stream,input){
                const reader=stream.readable.getReader(),writer=stream.writable.getWriter();
                const writing=(async()=>{await writer.write(input);await writer.close()})();
                const parts=[];let size=0;
                for(;;){const item=await reader.read();if(item.done)break;parts.push(item.value);size+=item.value.length}
                await writing;const bytes=new Uint8Array(size);let at=0;
                for(const part of parts){bytes.set(part,at);at+=part.length}return bytes;
            }
            const output={};
            for(const format of ['gzip','deflate','deflate-raw','brotli']){
                const bytes=await convert(new CompressionStream(format),new TextEncoder().encode('Mac 中文🦊'));
                output[format]=new TextDecoder().decode(await convert(new DecompressionStream(format),bytes));
            }
            result=output;
        })().catch(e=>result={error:String(e)});undefined''')
        self.assertEqual(self.await_value(),dict.fromkeys(['gzip','deflate','deflate-raw','brotli'],'Mac 中文🦊'))


    def test_webcrypto_digest_and_authenticated_encryption(self):
        self.context.load_page("https://example.test/", "<!doctype html><body></body>")
        self.context.eval('''globalThis.result=null;(async()=>{
            const sha=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode('abc'))))
                .map(b=>b.toString(16).padStart(2,'0')).join('');
            const key=await crypto.subtle.importKey('raw',new Uint8Array(16),'AES-GCM',false,['encrypt','decrypt']);
            const cipher=new Uint8Array(await crypto.subtle.encrypt({name:'AES-GCM',iv:new Uint8Array(12)},key,new Uint8Array(16)));
            const hex=Array.from(cipher).map(b=>b.toString(16).padStart(2,'0')).join('');
            const plain=await crypto.subtle.decrypt({name:'AES-GCM',iv:new Uint8Array(12)},key,cipher);
            cipher[cipher.length-1]^=1;let rejected=false;
            try{await crypto.subtle.decrypt({name:'AES-GCM',iv:new Uint8Array(12)},key,cipher)}catch(e){rejected=true}
            result={sha,hex,size:plain.byteLength,rejected};
        })().catch(e=>result={error:String(e)});undefined''')
        self.assertEqual(self.await_value(), {
            "sha":"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            "hex":"0388dace60b6a392f328c2b971b2fe78ab6e47d42cec13bdf53a67b21257bddf",
            "size":16,"rejected":True})


    def test_webcrypto_hmac_cbc_and_elliptic_curves(self):
        self.context.load_page("https://example.test/", "<!doctype html><body></body>")
        self.context.eval('''globalThis.result=null;(async()=>{
            const message=new TextEncoder().encode('Hi There');
            const hmac=await crypto.subtle.importKey('raw',new Uint8Array(20).fill(11),{name:'HMAC',hash:'SHA-256'},false,['sign']);
            const signed=new Uint8Array(await crypto.subtle.sign('HMAC',hmac,message));
            const hex=Array.from(signed).map(b=>b.toString(16).padStart(2,'0')).join('');
            const key=await crypto.subtle.importKey('raw',new Uint8Array(16),'AES-CBC',false,['encrypt','decrypt']);
            const params={name:'AES-CBC',iv:new Uint8Array(16)};
            const encrypted=await crypto.subtle.encrypt(params,key,new Uint8Array([1,2,3]));
            const plain=Array.from(new Uint8Array(await crypto.subtle.decrypt(params,key,encrypted)));
            const curves=[];
            for(const namedCurve of ['P-256','P-384','P-521']){
                const signing=await crypto.subtle.generateKey({name:'ECDSA',namedCurve},true,['sign','verify']);
                const signature=await crypto.subtle.sign({name:'ECDSA',hash:'SHA-256'},signing.privateKey,message);
                const valid=await crypto.subtle.verify({name:'ECDSA',hash:'SHA-256'},signing.publicKey,signature,message);
                const invalid=await crypto.subtle.verify({name:'ECDSA',hash:'SHA-256'},signing.publicKey,signature,new Uint8Array([1]));
                const a=await crypto.subtle.generateKey({name:'ECDH',namedCurve},true,['deriveBits']);
                const b=await crypto.subtle.generateKey({name:'ECDH',namedCurve},true,['deriveBits']);
                const first=new Uint8Array(await crypto.subtle.deriveBits({name:'ECDH',public:b.publicKey},a.privateKey,128));
                const second=new Uint8Array(await crypto.subtle.deriveBits({name:'ECDH',public:a.publicKey},b.privateKey,128));
                curves.push(valid&&!invalid&&first.every((v,i)=>v===second[i]));
            }
            result={hex,plain,curves};
        })().catch(e=>result={error:String(e)});undefined''')
        self.assertEqual(self.await_value(), {"hex":"b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7",
                                             "plain":[1,2,3],"curves":[True,True,True]})
