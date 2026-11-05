"""Fixtures for network attribution metrics and a real loopback data-path check."""
import threading
import unittest
from http.server import ThreadingHTTPServer
from analyze_network import percentile,summarize,socket_rtts,ping_mean,netem_drops
from client import request
from serve import Handler


class NetworkTests(unittest.TestCase):
    def test_percentiles_missing_and_nearest_rank(self):
        self.assertIsNone(percentile([], .95))
        self.assertEqual(percentile([None,1,2,3,4],.95),4)

    def test_failure_denominators_and_missing_iperf(self):
        capture={'requests':[{'scheduled_s':2,'correct':True,'status':200,'latency_ms':10},
                             {'scheduled_s':3,'correct':False,'status':None,'latency_ms':5000}], 'bulk':[]}
        result=summarize(capture)
        self.assertEqual(result['stable_arrivals'],2)
        self.assertEqual(result['stable_errors'],1)
        self.assertEqual(result['http_p95_ms'],10)
        self.assertIsNone(result['handler_p95_ms'])
        self.assertIsNone(result['iperf_sender_retransmits'])

    def test_boundary_selection(self):
        capture={'requests':[{'scheduled_s':i,'correct':True,'status':200,'latency_ms':i}for i in [0,2,17.8,18]],'bulk':[]}
        self.assertEqual(summarize(capture)['stable_arrivals'],2)

    def test_iperf_receiver_rate_and_sender_retries(self):
        result=summarize({'requests':[],'bulk':[]},{'end':{'sum_received':{'bits_per_second':4500000},'sum_sent':{'retransmits':3}}})
        self.assertEqual(result['iperf_received_mbps'],4.5)
        self.assertEqual(result['iperf_sender_retransmits'],3)

    def test_iperf_errors_are_preserved(self):
        result=summarize({'requests':[],'bulk':[]},{'error':'timeout'})
        self.assertEqual(result['iperf_error'],'timeout')
        self.assertIsNone(result['iperf_received_mbps'])

    def test_socket_scope_omits_ssh_and_keeps_test_rtt(self):
        text='ESTAB 0 0 lab-server:22 lab-client:4000\n rtt:1.0/0.1\nESTAB 0 0 lab-server:5201 lab-client:4001\n rtt:51.2/1.0\n'
        self.assertEqual(socket_rtts(text),[51.2])

    def test_ping_is_independent_and_missing_is_unknown(self):
        self.assertEqual(ping_mean('rtt min/avg/max/mdev = 0.1/0.2/0.3/0.1 ms'),.2)
        self.assertIsNone(ping_mean('100% packet loss'))

    def test_netem_counter_scope(self):
        text='qdisc prio 1: root\n Sent 100 bytes 20 pkt (dropped 99, overlimits 0)\nqdisc netem 30: parent 1:3\n Sent 90 bytes 18 pkt (dropped 3, overlimits 0)\n'
        self.assertEqual(netem_drops(text),3)
        self.assertIsNone(netem_drops('no queue'))

    def test_loopback_integrity_and_slow_handler(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            for path in ['/small','/large','/small?pause_ms=100']:
                result=request('127.0.0.1',server.server_port,path)
                self.assertTrue(result['correct'],result)
                if 'pause' in path:self.assertGreaterEqual(result['handler_ms'],95)
        finally:
            server.shutdown();server.server_close();thread.join(timeout=2)


if __name__=='__main__':unittest.main()
