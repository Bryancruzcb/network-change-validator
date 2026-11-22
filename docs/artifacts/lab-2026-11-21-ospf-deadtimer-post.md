# Change validation — devnet-default-lab-ospf-deadtimer

Findings: **2**

| policy | device | path | why |
|---|---|---|---|
| V\_ADJ | R1 | ospf.neighbors.2.2.2.2 | required OSPF neighbor 2.2.2.2 must be FULL on Ethernet0/1 |
| V\_ADJ | R2 | ospf.neighbors.1.1.1.1 | required OSPF neighbor 1.1.1.1 must be FULL on Ethernet0/1 |

_ncv 0.1.0, report format 1._
