import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import network_dns


class NetworkDnsTests(unittest.TestCase):
    def setUp(self):
        self.rows=network_dns.parse_dns_server_rows(json.dumps([
            {"InterfaceAlias":"Wi-Fi","InterfaceIndex":7,"AddressFamily":2,"ServerAddresses":["192.0.2.53"]},
            {"InterfaceAlias":"Wi-Fi","InterfaceIndex":7,"AddressFamily":23,"ServerAddresses":["2001:db8::53"]},
            {"InterfaceAlias":"Ethernet","InterfaceIndex":9,"AddressFamily":"IPv4","ServerAddresses":[]},
            {"InterfaceAlias":"Ethernet","InterfaceIndex":9,"AddressFamily":"IPv6","ServerAddresses":[]},
        ]))

    def test_parse_server_records_and_normalize_address_families(self):
        self.assertEqual(self.rows[7]["ipv4"]["servers"],["192.0.2.53"])
        self.assertEqual(self.rows[7]["ipv6"]["servers"],["2001:db8::53"])
        self.assertEqual(self.rows[9]["alias"],"Ethernet")
        with self.assertRaises(network_dns.DnsConfigurationError):
            network_dns.parse_dns_server_rows("{broken")

    def test_netsh_reports_mode_and_registration_and_unknown_is_not_guessed(self):
        output='''Configuration for interface "Wi-Fi"\n    Statically configured DNS servers: 192.0.2.53\n    Register with which suffix: Primary only\n\nConfiguration for interface "Ethernet"\n    DNS servers configured through DHCP: None\n    Register with which suffix: Both\n'''
        parsed=network_dns.parse_netsh_dns_report(output)
        self.assertEqual(parsed["wi-fi"]["source"],"static")
        self.assertEqual(parsed["wi-fi"]["register"],"primary")
        self.assertEqual(parsed["ethernet"]["source"],"dhcp")
        self.assertEqual(parsed["ethernet"]["register"],"both")
        self.assertIsNone(network_dns.parse_netsh_dns_report('Configuration for interface "Other"\n') ["other"]["source"])

    def test_ipv6_default_route_selects_lowest_metric_interface_index(self):
        output="""Active Routes:
 If Metric Network Destination      Gateway
  9    400 ::/0                    fe80::1
  7    200 ::/0                    fe80::2
  3    300 2001:db8::/64            On-link
"""
        self.assertEqual(network_dns.parse_ipv6_default_route_index(output),7)
        self.assertIsNone(network_dns.parse_ipv6_default_route_index("No IPv6 default route"))

    def test_adapter_source_support_is_per_family_and_fail_closed(self):
        v4=network_dns.parse_netsh_dns_report('''Configuration for interface "Wi-Fi"\n DNS servers configured through DHCP: 192.0.2.1\n Register with which suffix: Both\nConfiguration for interface "Ethernet"\n Statically configured DNS servers: 192.0.2.2\n Register with which suffix: Primary only''')
        v6=network_dns.parse_netsh_dns_report('''Configuration for interface "Wi-Fi"\n DNS servers configured through DHCP: 2001:db8::1\n Register with which suffix: Both\nConfiguration for interface "Ethernet"\n Statically configured DNS servers: None\n Register with which suffix: Primary only''')
        adapters=network_dns.build_dns_adapters(self.rows,v4,v6,"Wi-Fi")
        self.assertTrue(adapters[0]["is_default_route"])
        self.assertTrue(adapters[0]["supported"])
        self.assertEqual(adapters[0]["families"]["ipv4"]["source"],"dhcp")
        self.assertEqual(adapters[1]["families"]["ipv6"]["source"],"static")
        del v6["wi-fi"]
        adapter=network_dns.build_dns_adapters(self.rows,v4,v6,"Wi-Fi")[0]
        self.assertFalse(adapter["supported"])
        self.assertIn("could not reliably report",adapter["families"]["ipv6"]["reason"])

    def test_query_uses_read_only_powershell_and_netsh_show_commands(self):
        calls=[]
        server_output=json.dumps([{"InterfaceAlias":"Wi-Fi","InterfaceIndex":7,"AddressFamily":"IPv4","ServerAddresses":["192.0.2.53"]},
                                  {"InterfaceAlias":"Wi-Fi","InterfaceIndex":7,"AddressFamily":"IPv6","ServerAddresses":["2001:db8::53"]}])
        outputs=[(0,server_output,""),
                 (0,'Configuration for interface "Wi-Fi"\n Statically configured DNS servers: 192.0.2.53\n Register with which suffix: Primary only',""),
                 (0,'Configuration for interface "Wi-Fi"\n Statically configured DNS servers: 2001:db8::53\n Register with which suffix: Primary only',""),
                 (0,"Active Routes:\n If Metric Network Destination Gateway\n 7 20 ::/0 fe80::1","")]
        def runner(args,timeout): calls.append(args); return outputs.pop(0)
        adapters,error=network_dns.query_dns_adapters(runner=runner,default_route_alias="Wi-Fi")
        self.assertEqual(error,""); self.assertEqual(len(adapters),1)
        self.assertEqual(adapters[0]["interface_index"],7); self.assertTrue(adapters[0]["supported"])
        self.assertIn("Get-DnsClientServerAddress",calls[0][-1])
        self.assertEqual(calls[1][:4],["netsh.exe","interface","ipv4","show"])
        self.assertEqual(calls[2][:4],["netsh.exe","interface","ipv6","show"])
        self.assertEqual(calls[3], ["route.exe","print","-6"])
        self.assertTrue(all("set" not in args for args in calls))

    def test_dns_target_validation_and_static_write_use_family_scoped_netsh_commands(self):
        snapshot={"families":{"ipv4":{"register":"primary"},"ipv6":{"register":"both"}}}
        target=network_dns.make_target(snapshot,"static",["1.1.1.1","2606:4700:4700::1111"])
        self.assertEqual(target[4]["servers"],["1.1.1.1"])
        self.assertEqual(target[6]["servers"],["2606:4700:4700::1111"])
        with self.assertRaises(network_dns.DnsConfigurationError): network_dns.validate_dns_addresses(["not-an-ip"])
        with self.assertRaises(network_dns.DnsConfigurationError): network_dns.validate_dns_addresses(["224.0.0.1"])
        calls=[]
        result=network_dns.set_dns_family(7,"Wi-Fi",4,target[4],runner=lambda args,timeout:(calls.append(args) or (0,"","")))
        self.assertEqual(result,""); self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][:5],["netsh.exe","interface","ipv4","set","dnsservers"])
        self.assertIn("name=Wi-Fi",calls[0]); self.assertIn("address=1.1.1.1",calls[0])
        self.assertTrue(all("powershell.exe" not in call for call in calls))

    def test_static_dns_adds_secondary_address_in_the_same_family_only(self):
        calls=[]
        network_dns.set_dns_family(7,"Wi-Fi",4,{"source":"static","servers":["1.1.1.1","1.0.0.1"],"register":"primary"},
            runner=lambda args,timeout:(calls.append(args) or (0,"","")))
        self.assertEqual(len(calls),2)
        self.assertIn("interface",calls[0]); self.assertIn("ipv4",calls[0]); self.assertIn("source=static",calls[0])
        self.assertIn("ipv4",calls[1]); self.assertIn("address=1.0.0.1",calls[1]); self.assertIn("index=2",calls[1])
        self.assertTrue(all("ipv6" not in call for call in calls))

    def test_dhcp_reset_is_family_scoped_and_uses_no_shell(self):
        calls=[]
        result=network_dns.set_dns_family(7,"Wi-Fi",6,{"source":"dhcp","servers":[],"register":"primary"},
            runner=lambda args,timeout:(calls.append(args) or (0,"reset","")))
        self.assertEqual(result,"reset")
        self.assertEqual(calls[0][:5],["netsh.exe","interface","ipv6","set","dnsservers"])
        self.assertIn("source=dhcp",calls[0]); self.assertIn("validate=no",calls[0])

    def test_restore_detects_conflict_and_restores_original_exact_family(self):
        old={"source":"static","servers":["192.0.2.53"],"register":"primary"}
        expected={"source":"static","servers":["1.1.1.1"],"register":"primary"}
        action={"type":"dns_family","interface_index":7,"alias":"Wi-Fi","family":4,"old":old,"expected":expected}
        now={"interface_index":7,"alias":"Wi-Fi","families":{"ipv4":expected,"ipv6":{"source":"dhcp","servers":[],"register":"both"}}}
        restore=Mock(return_value="restored"); readers=[ [now], [dict(now,families={**now["families"],"ipv4":old})] ]
        ok,message=network_dns.restore_dns_action(action,reader=lambda:readers.pop(0),runner=lambda args,timeout:(0,"",""))
        self.assertTrue(ok,message); self.assertIn("restored",message)
        changed=dict(now,families={**now["families"],"ipv4":{"source":"static","servers":["9.9.9.9"],"register":"primary"}})
        ok,message=network_dns.restore_dns_action(action,reader=lambda:[changed],runner=lambda *args,**kwargs: self.fail("conflicts must not write"))
        self.assertFalse(ok); self.assertIn("newer configuration untouched",message)

    def test_undo_accepts_only_known_partial_static_write_prefixes(self):
        old={"source":"dhcp","servers":[],"register":"primary"}
        expected={"source":"static","servers":["1.1.1.1","1.0.0.1"],"register":"primary"}
        action={"type":"dns_family","interface_index":7,"alias":"Wi-Fi","family":4,"old":old,"expected":expected,
                "expected_variants":network_dns.possible_write_results(expected)}
        partial={"source":"static","servers":["1.1.1.1"],"register":"primary"}
        row={"interface_index":7,"alias":"Wi-Fi","families":{"ipv4":partial}}
        restored={"interface_index":7,"alias":"Wi-Fi","families":{"ipv4":old}}
        reads=[[row],[restored]]
        ok,message=network_dns.restore_dns_action(action,reader=lambda:reads.pop(0),runner=lambda *a,**k:(0,"",""))
        self.assertTrue(ok,message)
        changed={"source":"static","servers":["9.9.9.9"],"register":"primary"}
        row["families"]["ipv4"]=changed
        ok,message=network_dns.restore_dns_action(action,reader=lambda:[row],runner=lambda *a,**k:self.fail("unrecognized external state must not write"))
        self.assertFalse(ok); self.assertIn("newer configuration untouched",message)

    def test_static_configuration_without_captured_servers_is_not_restorable(self):
        rows={1:{"interface_index":1,"alias":"Ethernet","ipv4":{"servers":[]},"ipv6":{"servers":[]}}}
        v4={"ethernet":{"source":"static","register":"both"}}
        v6={"ethernet":{"source":"dhcp","register":"both"}}
        adapter=network_dns.build_dns_adapters(rows,v4,v6)[0]
        self.assertFalse(adapter["families"]["ipv4"]["supported"])
        self.assertIn("no restorable server address",adapter["families"]["ipv4"]["reason"])

    def test_dynamic_dhcp_addresses_can_change_without_false_conflict(self):
        old={"source":"dhcp","servers":["192.0.2.1"],"register":"both"}
        now={"source":"dhcp","servers":["192.0.2.99"],"register":"both"}
        self.assertTrue(network_dns.config_matches(now,old))

    def test_permission_errors_are_reported_without_attempting_elevation(self):
        with self.assertRaises(PermissionError):
            network_dns.set_dns_family(7,"Wi-Fi",4,{"source":"static","servers":["1.1.1.1"],"register":"primary"},
                runner=lambda *args,**kwargs:(1,"","Access is denied"))


if __name__=="__main__": unittest.main(verbosity=2)
