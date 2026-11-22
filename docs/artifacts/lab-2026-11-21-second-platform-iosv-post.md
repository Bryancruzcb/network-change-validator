# Change validation — devnet-default-lab-second-platform

Findings: **9**

| policy | device | path | why |
|---|---|---|---|
| V\_ADJ | R1 | ospf.neighbors.3.3.3.3 | required OSPF neighbor 3.3.3.3 must be FULL on Ethernet0/3 |
| V\_ADJ | R3 | ospf.neighbors.1.1.1.1 | required OSPF neighbor 1.1.1.1 must be FULL on GigabitEthernet0/0 |
| V\_ADJ | R1 | bgp.vrfs.default.neighbors.10.1.3.3 | required BGP neighbor 10.1.3.3 must be Established in vrf default with remote AS 65003 |
| V\_ADJ | R3 | bgp.vrfs.default.neighbors.10.1.3.1 | required BGP neighbor 10.1.3.1 must be Established in vrf default with remote AS 65001 |
| V\_ROUTE | R1 | routing.vrfs.default.routes.10.1.3.0/24 | required prefix 10.1.3.0/24 missing from R1 vrf default |
| V\_ROUTE | R1 | routing.vrfs.default.routes.3.3.3.3/32 | required prefix 3.3.3.3/32 missing from R1 vrf default |
| V\_ROUTE | R1 | routing.vrfs.default.routes.172.16.3.0/24 | required prefix 172.16.3.0/24 missing from R1 vrf default |
| V\_ROUTE | R3 | routing.vrfs.default.routes.1.1.1.0/24 | required prefix 1.1.1.0/24 missing from R3 vrf default |
| V\_ROUTE | R3 | routing.vrfs.default.routes.10.10.10.0/24 | required prefix 10.10.10.0/24 missing from R3 vrf default |

_ncv 0.1.0, report format 1._
