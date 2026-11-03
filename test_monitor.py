import copy
import json
from pathlib import Path
import tempfile
import unittest
from monitor import build_report, derive, snapshot


class MonitoringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'stat').write_text('cpu 100 0 100 700 50 20 20 10 30 0\ncpu0 0\ncpu1 0\nprocs_running 2\nprocs_blocked 1\n')
        (self.root / 'meminfo').write_text('MemTotal: 10000 kB\nMemAvailable: 4000 kB\nCached: 2000 kB\nSwapTotal: 1000 kB\nSwapFree: 500 kB\n')
        (self.root / 'loadavg').write_text('2.0 1.0 0.5 2/99 123')
        (self.root / 'diskstats').write_text('8 0 sda 10 0 100 20 10 0 100 20 0 50 100\n')
        (self.root / 'net').mkdir()
        (self.root / 'net/dev').write_text('Inter-| Receive | Transmit\n eth0: 1000 1 0 0 0 0 0 0 2000 1 0 0 0 0 0 0\n')
        (self.root / 'pressure').mkdir()
        for r in ('cpu', 'memory', 'io'):
            (self.root / 'pressure' / r).write_text('some avg10=1.0 avg60=0.5 avg300=0.1 total=1000\nfull avg10=0.1 avg60=0.1 avg300=0.0 total=500\n')
        self.a = snapshot(self.root)
        self.a['mono'] = 10
        self.b = copy.deepcopy(self.a)
        self.b['mono'] = 12
        self.b['cpu'] = [120, 0, 110, 750, 60, 25, 25, 10]

    def test_cpu_denominator_excludes_duplicate_guest_fields(self):
        self.assertEqual(len(self.a['cpu']), 8)
        result = derive(self.a, self.b)
        self.assertEqual(result['cpu_busy_pct'], 40)
        self.assertEqual(result['cpu_iowait_pct'], 10)

    def test_cpu_reset_is_not_zero_utilization(self):
        self.b['cpu'][0] = 1
        self.assertIsNone(derive(self.a, self.b)['cpu_busy_pct'])

    def test_hotplug_invalidates_cpu_interval(self):
        self.b['cores'] = 3
        self.assertIsNone(derive(self.a, self.b)['cpu_busy_pct'])

    def test_missing_psi_remains_unknown(self):
        (self.root / 'pressure/io').unlink()
        b = snapshot(self.root)
        b['mono'] = 12
        result = derive(self.a, b)
        self.assertEqual(result['psi']['io'], {})
        self.assertTrue(any('pressure/io' in w for w in result['warnings']))

    def test_psi_microseconds_and_system_cpu_full(self):
        self.b['psi']['cpu']['some']['total'] += 200000
        result = derive(self.a, self.b)
        self.assertEqual(result['psi']['cpu']['some'], 10)
        self.assertNotIn('full', result['psi']['cpu'])

    def test_psi_reset_unknown(self):
        self.b['psi']['memory']['some']['total'] = 0
        self.assertIsNone(derive(self.a, self.b)['psi']['memory']['some'])

    def test_device_rates_use_actual_elapsed_time(self):
        self.b['disk']['sda'] = [12, 0, 4196, 60, 12, 0, 4196, 60, 0, 1050, 2100]
        result = derive(self.a, self.b)['disk']['sda']
        self.assertEqual(result['read_mib_s'], 1)
        self.assertEqual(result['rw_iops'], 2)
        self.assertEqual(result['rw_await_ms'], 20)
        self.assertEqual(result['avg_queue'], 1)
        self.assertEqual(result['busy_pct'], 50)

    def test_no_completions_await_is_unknown(self):
        self.assertIsNone(derive(self.a, self.b)['disk']['sda']['rw_await_ms'])

    def test_device_reset_omitted(self):
        self.b['disk']['sda'][0] = 0
        self.assertNotIn('sda', derive(self.a, self.b)['disk'])

    def test_network_errors_drops_and_bytes(self):
        self.b['net']['eth0'][0] += 2097152
        self.b['net']['eth0'][2] += 4
        self.b['net']['eth0'][11] += 2
        result = derive(self.a, self.b)['net']['eth0']
        self.assertEqual(result['rx_mib_s'], 1)
        self.assertEqual(result['errors_s'], 2)
        self.assertEqual(result['drops_s'], 1)

    def test_network_reset_is_not_negative_rate(self):
        self.b['net']['eth0'][0] = 0
        self.assertNotIn('eth0', derive(self.a, self.b)['net'])

    def test_memory_available_not_free(self):
        self.assertEqual(derive(self.a, self.b)['mem_available_pct'], 40)
        del self.b['mem']['MemAvailable']
        self.assertIsNone(derive(self.a, self.b)['mem_available_pct'])

    def test_invalid_time_rejected(self):
        self.b['mono'] = 10
        with self.assertRaises(ValueError):
            derive(self.a, self.b)

    def test_report_cannot_be_broken_out_of_json_script(self):
        path = self.root / 'report.html'
        data = {'title': '</script><script>alert(1)</script>', 'samples': []}
        build_report(data, path)
        html = path.read_text(encoding='utf-8')
        self.assertNotIn(data['title'], html)
        self.assertIn('\\u003c/script\\u003e', html)
        self.assertNotIn('__CAPTURE_DATA__', html)


if __name__ == '__main__':
    unittest.main()
