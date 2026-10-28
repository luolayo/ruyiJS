"use strict";

const results = {};
assertEq(getBuildConfiguration().arm64, true);
results.arm64 = true;

let reachedIon = false;
function hot(value) {
  if (inIon()) reachedIon = true;
  return value * 3 + 1;
}
for (let i = 0; i < 10000; i++) assertEq(hot(i), i * 3 + 1);
assertEq(reachedIon, true);
results.ion = true;

let promiseValue = 0;
Promise.resolve(21).then(value => { promiseValue = value * 2; });
drainJobQueue();
assertEq(promiseValue, 42);
results.promise = true;

const wasm = new WebAssembly.Instance(new WebAssembly.Module(wasmTextToBinary(
  '(module (func (export "answer") (result i32) i32.const 42))')));
assertEq(wasm.exports.answer(), 42);
results.wasm = true;

assertEq(/\p{Script=Han}+/u.exec("abc中文🦊")[0], "中文");
assertEq(String(9007199254740993n + 7n), "9007199254741000");
assertEq(new Intl.DateTimeFormat("en", {timeZone: "Asia/Shanghai"})
  .resolvedOptions().timeZone, "Asia/Shanghai");
results.regexpBigIntIntl = true;

const retained = {text: "UTF-8 中文🦊", values: new Uint32Array([1, 2, 4294967295])};
gc();
assertEq(retained.text, "UTF-8 中文🦊");
assertEq(retained.values[2], 4294967295);
results.gc = true;

const codec = evaluate(read(scriptArgs[0]));
const reply = JSON.parse(codec.reply(7, true, [undefined, -0, 12345678901234567890n, "中文"]));
assertEq(reply.id, 7);
assertEq(reply.value.value[0].type, "undefined");
assertEq(reply.value.value[1].value, "-0");
assertEq(reply.value.value[2].value, "12345678901234567890");
assertEq(reply.value.value[3].value, "中文");
const cyclic = {};
cyclic.self = cyclic;
let rejected = false;
try { codec.reply(8, true, cyclic); } catch (error) { rejected = error instanceof TypeError; }
assertEq(rejected, true);
results.productCodec = true;

print(JSON.stringify(results));
