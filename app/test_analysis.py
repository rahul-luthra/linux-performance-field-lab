import unittest
from analyze_app import percentile, summarize


class AnalysisTests(unittest.TestCase):
    def test_nearest_rank_percentiles(self):
        self.assertEqual(percentile(list(range(1, 101)), .95), 95)
        self.assertEqual(percentile(list(range(1, 101)), .99), 99)
        self.assertEqual(percentile([1, 2, 3, 100], .95), 100)

    def test_missing_percentile_is_unknown(self):
        self.assertIsNone(percentile([], .95))

    def test_failures_remain_in_denominator(self):
        rows = [dict(index=0, scheduled_s=3, status=200, quote=101.052403, scheduler_lag_ms=0,
                     latency_ms=100, handler_wall_ms=80, handler_cpu_ms=70),
                dict(index=1, scheduled_s=4, status=0, error='client rejected')]
        baseline = summarize({'requests': rows, 'samples': []})['baseline']
        self.assertEqual(baseline['offered_requests'], 2)
        self.assertEqual(baseline['errors_or_rejected'], 1)
        self.assertEqual(baseline['latency_ms']['p95'], 100)

    def test_completion_window_uses_completion_time(self):
        row = dict(index=0, scheduled_s=1.9, status=200, quote=101.052403, scheduler_lag_ms=0,
                   latency_ms=200, handler_wall_ms=180, handler_cpu_ms=70)
        baseline = summarize({'requests': [row], 'samples': []})['baseline']
        self.assertEqual(baseline['offered_requests'], 0)
        self.assertEqual(baseline['successful_completions_per_second'], .062)

    def test_wrong_response_does_not_count_as_success(self):
        row = dict(index=0, scheduled_s=3, status=200, quote=0, scheduler_lag_ms=0,
                   latency_ms=100, handler_wall_ms=80, handler_cpu_ms=70)
        baseline = summarize({'requests': [row], 'samples': []})['baseline']
        self.assertEqual(baseline['errors_or_rejected'], 1)
        self.assertIsNone(baseline['latency_ms']['p95'])
        self.assertEqual(baseline['successful_completions_per_second'], 0)


if __name__ == '__main__':
    unittest.main()
