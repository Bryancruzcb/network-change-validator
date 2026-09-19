# Change validation — demo-campus-core

Findings: **8**

| policy | device | path | why |
|---|---|---|---|
| V\_ADJ | r1 | ospf.neighbors.10.0.12.2 | required OSPF neighbor 10.0.12.2 must be FULL on GigabitEthernet0/1 |
| V\_ADJ | r2 | ospf.neighbors.10.0.12.1 | required OSPF neighbor 10.0.12.1 must be FULL on GigabitEthernet0/1 |
| V\_ADJ | r1 | bgp.neighbors.203.0.113.1 | required BGP neighbor 203.0.113.1 must be Established in vrf default with remote AS 65100 |
| V\_ROUTE | r1 | routing.vrfs.default.routes.10.20.0.0/24 | required prefix 10.20.0.0/24 missing from r1 vrf default |
| V\_ROUTE | r2 | routing.vrfs.default.routes.10.10.0.0/24 | required prefix 10.10.0.0/24 missing from r2 vrf default |
| V\_ERR | r1 | interface.GigabitEthernet0/1.counters | GigabitEthernet0/1 errors in\_errors=42 (max 10), crc=9 (max 5) |
| V\_DRIFT | r1 | config.running.must\_include | required line missing: ntp server 192.0.2.1 |
| V\_DRIFT | r1 | config.running.must\_absent | forbidden line present: username leftover privilege 15 |

_ncv 0.1.0, report format 1._
