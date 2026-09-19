# Change validation — devnet-default-lab-ospf

Findings: **4**

| policy | device | path | why |
|---|---|---|---|
| V\_ADJ | R1 | ospf.neighbors.2.2.2.2 | required OSPF neighbor 2.2.2.2 must be FULL on Ethernet0/1 |
| V\_ADJ | R2 | ospf.neighbors.1.1.1.1 | required OSPF neighbor 1.1.1.1 must be FULL on Ethernet0/1 |
| V\_ROUTE | R1 | routing.vrfs.default.routes.20.20.20.0/24 | required prefix 20.20.20.0/24 missing from R1 vrf default |
| V\_ROUTE | R1 | routing.vrfs.default.routes.1.1.1.0/24 | required prefix 1.1.1.0/24 missing from R1 vrf default |

_ncv 0.1.0, report format 1._
