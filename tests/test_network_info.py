import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import network_info


class NetworkInfoTests(unittest.TestCase):
    def setUp(self):
        self.addresses={
            "Wi-Fi":[SimpleNamespace(family="AF_INET",address="10.0.0.9"),SimpleNamespace(family="AF_INET6",address="2001:db8::9")],
            "Ethernet":[SimpleNamespace(family="AF_INET",address="192.0.2.3")],
        }
        self.stats={"Wi-Fi":SimpleNamespace(isup=True,speed=866),"Ethernet":SimpleNamespace(isup=False,speed=0)}

    def test_dns_normalization_and_default_route_parsing(self):
        data=[{"InterfaceAlias":"Wi-Fi","ServerAddresses":["10.0.0.1","10.0.0.1"]},{"InterfaceAlias":"Wi-Fi","ServerAddresses":[]},{"InterfaceAlias":"Ethernet","ServerAddresses":["192.0.2.1"]}]
        dns=network_info.parse_dns_records(json.dumps(data))
        self.assertEqual(dns["wi-fi"],["10.0.0.1"])
        route="""Network Destination Netmask Gateway Interface Metric
0.0.0.0 0.0.0.0 192.0.2.1 192.0.2.3 25
0.0.0.0 0.0.0.0 10.0.0.1 10.0.0.9 35
"""
        self.assertEqual(network_info.parse_default_route_interface(route),"192.0.2.3")
        rows=network_info.build_adapter_records(self.addresses,self.stats,dns,"10.0.0.9")
        self.assertEqual(rows[0]["name"],"Wi-Fi")
        self.assertEqual(rows[0]["link_speed"],"866 Mbps")
        self.assertEqual(rows[0]["dns_servers"],["10.0.0.1"])
        self.assertTrue(rows[0]["has_default_route"])
        self.assertFalse(rows[1]["has_default_route"])

    def test_query_uses_only_read_commands_and_reports_partial_failures(self):
        outputs=[(0,json.dumps({"InterfaceAlias":"Wi-Fi","ServerAddresses":["10.0.0.1"]}),""),(0,"0.0.0.0 0.0.0.0 10.0.0.1 10.0.0.9 25","" )]
        calls=[]
        def runner(args,timeout): calls.append((args,timeout)); return outputs.pop(0)
        rows,error=network_info.query_adapters(self.addresses,self.stats,runner=runner)
        self.assertEqual(error,""); self.assertEqual(rows[0]["name"],"Wi-Fi")
        self.assertEqual(len(calls),2); self.assertIn("Get-DnsClientServerAddress",calls[0][0][-1]); self.assertIn("route.exe",calls[1][0][0])
        self.assertTrue(all("Set-" not in " ".join(call[0]) for call in calls))
        rows,error=network_info.query_adapters(self.addresses,self.stats,runner=lambda *args,**kwargs:(1,"","denied"))
        self.assertTrue(rows); self.assertIn("denied",error)

    def test_malformed_dns_is_rejected_and_missing_route_is_unknown(self):
        with self.assertRaises(network_info.NetworkQueryError): network_info.parse_dns_records("{broken")
        rows=network_info.build_adapter_records(self.addresses,self.stats,{},None)
        self.assertIsNone(next(item for item in rows if item["name"]=="Wi-Fi")["has_default_route"])


if __name__=="__main__": unittest.main(verbosity=2)
