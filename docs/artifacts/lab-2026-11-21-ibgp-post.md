# Change validation — devnet-default-lab-ibgp

Findings: **8**

| policy | device | path | why |
|---|---|---|---|
| V\_ADJ | R1 | ospf.neighbors.2.2.2.2 | required OSPF neighbor 2.2.2.2 must be FULL on Ethernet0/1 |
| V\_ADJ | R2 | ospf.neighbors.1.1.1.1 | required OSPF neighbor 1.1.1.1 must be FULL on Ethernet0/1 |
| V\_ADJ | R1 | bgp.vrfs.default.neighbors.10.255.255.2 | required BGP neighbor 10.255.255.2 must be Established in vrf default with remote AS 65010 |
| V\_ADJ | R2 | bgp.vrfs.default.neighbors.10.255.255.1 | required BGP neighbor 10.255.255.1 must be Established in vrf default with remote AS 65010 |
| V\_ROUTE | R1 | routing.vrfs.default.routes.10.255.255.2/32 | required prefix 10.255.255.2/32 missing from R1 vrf default |
| V\_ROUTE | R1 | routing.vrfs.default.routes.172.16.2.0/24 | required prefix 172.16.2.0/24 missing from R1 vrf default |
| V\_ROUTE | R2 | routing.vrfs.default.routes.10.255.255.1/32 | required prefix 10.255.255.1/32 missing from R2 vrf default |
| V\_ROUTE | R2 | routing.vrfs.default.routes.172.16.1.0/24 | required prefix 172.16.1.0/24 missing from R2 vrf default |

_ncv 0.1.0, report format 1._
