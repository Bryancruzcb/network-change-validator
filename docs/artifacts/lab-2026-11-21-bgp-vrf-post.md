# Change validation — devnet-default-lab-bgp-vrf

Findings: **5**

| policy | device | path | why |
|---|---|---|---|
| V\_ADJ | R1 | bgp.vrfs.NCV.neighbors.1.1.1.2 | required BGP neighbor 1.1.1.2 must be Established in vrf NCV with remote AS 65002 |
| V\_ADJ | R2 | bgp.vrfs.NCV.neighbors.1.1.1.1 | required BGP neighbor 1.1.1.1 must be Established in vrf NCV with remote AS 65001 |
| V\_ROUTE | R1 | routing.vrfs.NCV.routes.1.1.1.0/24 | required prefix 1.1.1.0/24 missing from R1 vrf NCV |
| V\_ROUTE | R1 | routing.vrfs.NCV.routes.172.16.102.0/24 | required prefix 172.16.102.0/24 missing from R1 vrf NCV |
| V\_ROUTE | R2 | routing.vrfs.NCV.routes.172.16.101.0/24 | required prefix 172.16.101.0/24 missing from R2 vrf NCV |

_ncv 0.1.0, report format 1._
