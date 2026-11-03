import unittest
from analyze_memory import classify, percentile, summarize_pressure, counter_delta


class MemoryEvidenceTests(unittest.TestCase):
    def test_heap_error_requires_jvm_evidence(self):
        data = {'java_returncode': 3, 'event_deltas': {'oom_kill': 0}}
        self.assertEqual(classify(data, 'java.lang.OutOfMemoryError: Java heap space'), 'Java heap exhaustion')
        self.assertIn('Inconclusive', classify(data, ''))

    def test_cgroup_kill_requires_signal_and_counter(self):
        self.assertEqual(classify({'java_returncode': -9, 'event_deltas': {'oom_kill': 1}}, ''), 'Linux cgroup OOM kill')
        self.assertIn('Inconclusive', classify({'java_returncode': -9, 'event_deltas': {'oom_kill': 0}}, ''))
        self.assertIn('Inconclusive', classify({'java_returncode': 3, 'event_deltas': {'oom_kill': 1}}, ''))

    def test_missing_counter_is_not_zero(self):
        self.assertIn('unavailable', classify({'java_returncode': -9}, ''))

    def test_bounded_completion_is_not_a_spontaneous_exit(self):
        data = {'allocation_complete': True, 'stopped_by_harness': True, 'event_deltas': {'oom_kill': 0}, 'java_returncode': 143}
        self.assertEqual(classify(data, ''), 'Bounded allocation completed')
        data['stopped_by_harness'] = False
        self.assertIn('Inconclusive', classify(data, ''))

    def test_percentile_small_sample_and_missing(self):
        self.assertEqual(percentile([1, 2, 3, 100], .95), 100)
        self.assertIsNone(percentile([], .95))

    def test_reset_or_missing_counter_is_unknown(self):
        self.assertIsNone(counter_delta({'gc_count': 10}, {'gc_count': 2}, 'gc_count'))
        self.assertIsNone(counter_delta({}, {'gc_count': 2}, 'gc_count'))

    def test_no_jvm_samples_remains_unknown(self):
        data = summarize_pressure({'requests': [], 'load_start_monotonic': 100}, {'samples': []})
        self.assertIsNone(data['baseline']['gc_count_delta'])
        self.assertIsNone(data['baseline']['gc_time_delta_ms'])

    def test_gc_counters_have_their_own_window(self):
        samples = [{'monotonic': 103, 'jvm': {'gc_count': 2, 'gc_ms': 10}, 'cgroup_current_bytes': 1},
                   {'monotonic': 112, 'jvm': {'gc_count': 6, 'gc_ms': 25}, 'cgroup_current_bytes': 1}]
        result = summarize_pressure({'requests': [], 'load_start_monotonic': 100}, {'samples': samples})['baseline']
        self.assertEqual(result['gc_count_delta'], 4)
        self.assertEqual(result['gc_time_delta_ms'], 15)
        self.assertEqual(result['gc_counter_window_s'], 9)

    def test_errors_and_wrong_checksum_stay_in_denominator(self):
        rows = [{'scheduled_s': 3, 'status': 0, 'error': 'timeout'},
                {'scheduled_s': 4, 'status': 200, 'quote': 101.052403, 'checksum': 1, 'latency_ms': 10, 'scheduler_lag_ms': 0}]
        result = summarize_pressure({'requests': rows, 'load_start_monotonic': 100}, {'samples': []})['baseline']
        self.assertEqual(result['arrivals'], 2)
        self.assertEqual(result['errors'], 2)
        self.assertIsNone(result['p95_ms'])
        self.assertEqual(result['completions_per_s'], 0)


if __name__ == '__main__': unittest.main()
