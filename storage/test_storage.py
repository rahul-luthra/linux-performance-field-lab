import unittest
from telemetry import mountstats,rpc_delta
from analyze_storage import device_summary,percentile,summarize

class StorageEvidenceTests(unittest.TestCase):
    def test_mountstats_selects_only_target_mount(self):
        text='device server:/one mounted on /mnt/other with fstype nfs4 statvers=1.1\n WRITE: 99 99 0 1 1 0 1 1 0\ndevice server:/two mounted on /mnt/perf-lab-nfs with fstype nfs4 statvers=1.1\n WRITE: 2 2 0 100 80 1 20 25 0\n'
        self.assertEqual(mountstats(text)['WRITE'][0],2)

    def test_rpc_units_and_retransmissions(self):
        result=rpc_delta({'WRITE':[10,10,0,100,50,0,50,60]}, {'WRITE':[12,13,1,300,150,4,70,90]})['WRITE']
        self.assertEqual(result['rtt_ms_mean'],10)
        self.assertEqual(result['execute_ms_mean'],15)
        self.assertEqual(result['queue_ms_mean'],2)
        self.assertEqual(result['retransmissions'],1)
        self.assertEqual(result['major_timeouts'],1)

    def test_counter_reset_is_omitted(self):
        self.assertEqual(rpc_delta({'WRITE':[10]*8},{'WRITE':[1]*8}),{})

    def test_no_operations_mean_unknown_latency(self):
        self.assertIsNone(rpc_delta({'COMMIT':[0]*8},{'COMMIT':[0]*8})['COMMIT']['rtt_ms_mean'])

    def test_missing_rpc_source_is_not_zero(self):
        self.assertEqual(rpc_delta({}, {'WRITE':[1]*8}),{})

    def test_rpc_inflight_difference_is_not_false_zero(self):
        self.assertIsNone(rpc_delta({'WRITE':[0]*8},{'WRITE':[2,1,0,0,0,0,0,0]})['WRITE']['retransmissions'])

    def test_disk_await_is_completion_weighted(self):
        def row(iops,wait):return {'interval_s':1,'disk':{'sda':{'rw_iops':iops,'rw_await_ms':wait,'avg_queue':0,'busy_pct':1,'write_mib_s':1}}}
        self.assertEqual(device_summary([row(1,10),row(9,2)])['rw_await_ms_weighted'],2.8)

    def test_missing_disk_is_unknown(self):
        self.assertIsNone(device_summary([])['rw_await_ms_weighted'])

    def test_percentile_and_empty(self):
        self.assertEqual(percentile([1,2,3,100],.95),100)
        self.assertIsNone(percentile([],.95))

    def test_failed_requests_stay_in_denominator_and_unknown_readback(self):
        capture={'name':'test','storage':'local','started_utc':'2026-01-01T00:00:00+00:00','finished_utc':'2026-01-01T00:00:30+00:00',
                 'requests':[{'scheduled_s':3,'status':0,'correct_response':False}],'verification':{}}
        result=summarize(capture,[],[],server_verification={'latest':{}})
        self.assertEqual(result['errors'],1)
        self.assertIsNone(result['p95_ms'])
        self.assertIsNone(result['server_readback_matches'])

if __name__=='__main__':unittest.main()
