# Change validation — devnet-default-lab-bgp

Findings: **3**

| policy | device | path | why |
|---|---|---|---|
| V\_ADJ | R1 | bgp.neighbors.1.1.1.2 | required BGP neighbor 1.1.1.2 must be Established in vrf default with remote AS 65002 |
| V\_ADJ | R2 | bgp.neighbors.1.1.1.1 | required BGP neighbor 1.1.1.1 must be Established in vrf default with remote AS 65001 |
| V\_DRIFT | R1 | config.running.must\_absent | forbidden line present: neighbor 1.1.1.2 shutdown |

_ncv 0.1.0, report format 1._
