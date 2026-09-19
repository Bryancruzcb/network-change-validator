# Change validation — devnet-default-lab-r1-r2

Findings: **2**

| policy | device | path | why |
|---|---|---|---|
| V\_ROUTE | R1 | routing.vrfs.default.routes.20.20.20.0/24 | required prefix 20.20.20.0/24 missing from R1 vrf default |
| V\_ROUTE | R1 | routing.vrfs.default.routes.1.1.1.0/24 | required prefix 1.1.1.0/24 missing from R1 vrf default |

_ncv 0.1.0, report format 1._
