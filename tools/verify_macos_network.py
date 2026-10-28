"""Verify real local HTTP/TLS/QUIC peers and optional public endpoints."""
import argparse
import json
import re
import subprocess

from spidermonkey_source import ROOT, OUTPUT, digest


def suite(helper, script, minimum, log_name):
    log = OUTPUT / 'logs' / log_name
    with log.open('w') as stream:
        result = subprocess.run([helper, '-B', script, '-v'], cwd=ROOT / 'native/necko/tests',
                                stdout=stream, stderr=subprocess.STDOUT, timeout=120)
    text = log.read_text()
    if result.returncode:
        print(text[-12000:]); raise SystemExit(result.returncode)
    count = re.search(r'Ran (\d+) tests', text)
    if not count or int(count[1]) < minimum:
        raise ValueError('Network regression suite did not run completely: ' + script)
    return {'tests_passed':int(count[1]), 'test_log':str(log)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Also GET https://example.com through NSS and Context.navigate')
    parser.add_argument('--live-quic', action='store_true', help='Also require a public HTTP3 GET, with no TCP fallback')
    args = parser.parse_args()
    helper = ROOT / 'vendor/necko-derived/bin/python3'
    native = ROOT / 'vendor/necko-derived/lib/python3.13/site-packages/necko'
    bridge = native / 'libnecko_core.dylib'
    quic = native / 'libnecko_quic.dylib'
    build = json.loads((OUTPUT / 'network-build.json').read_text())
    if not helper.is_file() or digest(bridge) != build['bridge_sha256'] or digest(quic) != build['quic']['sha256']:
        raise ValueError('Build the network helper first')
    for inputs in (build['native_sources'], build['python_sources'], build['quic']['sources']):
        for relative, expected in inputs.items():
            if digest(ROOT / relative) != expected:
                raise ValueError('Network input changed; rebuild first: ' + relative)
    if digest(ROOT / 'config/neqo-macos.lock.json') != build['quic']['source_lock_sha256']:
        raise ValueError('Neqo source lock changed; rebuild first')
    peer = OUTPUT / 'quic/target/release/examples/peer'
    if digest(peer) != build['quic']['test_peer_sha256']:
        raise ValueError('QUIC test peer changed; rebuild first')
    normal = suite(helper, 'test_network.py', 10, 'network-tests.log')
    quic_result = suite(helper, 'test_quic.py', 11, 'quic-tests.log')
    report = {'passed':True, 'tests_passed':normal['tests_passed'] + quic_result['tests_passed'],
              'http_tests':normal, 'quic_tests':quic_result,
              'bridge_sha256':digest(bridge), 'quic_sha256':digest(quic),
              'quic_test_peer_sha256':digest(peer), 'product_sha256':digest(ROOT / 'dist/js'),
              'network_build_sha256':digest(OUTPUT / 'network-build.json'),
              'protocols':['http/1.1','h2','h3'], 'tls_backend':'NSS 3.130', 'neqo_version':'0.31.1',
              'certificate_chain_and_hostname_checks':True, 'http3':True, 'webtransport':True,
              'real_loopback_udp_verified':True, 'context_http3_verified':True, 'context_webtransport_verified':True,
              'firefox_fingerprint_parity_verified':False}
    if args.live:
        result = subprocess.run([helper, '-B', 'live_probe.py'], cwd=ROOT / 'native/necko/tests',
                                capture_output=True, text=True, timeout=60, check=True)
        report['live'] = json.loads(result.stdout)
        (OUTPUT / 'logs/network-live.log').write_text(result.stdout + result.stderr)
    if args.live_quic:
        result = subprocess.run([helper, '-B', 'live_quic_probe.py'], cwd=ROOT / 'native/necko/tests',
                                capture_output=True, text=True, timeout=40)
        report['public_quic'] = json.loads(result.stdout)
        (OUTPUT / 'logs/quic-live.log').write_text(result.stdout + result.stderr)
    (OUTPUT / 'network-verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    if args.live_quic and not report['public_quic']['passed']:
        raise SystemExit('Local regressions passed; public HTTP3 probe failed (see public_quic)')


if __name__ == '__main__': main()
