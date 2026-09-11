# Live path

Default CI never SSHes anywhere. Live capture is optional and locked behind `--i-am-in-a-lab`.

## What you need

One of:

1. CML Free on a PC/VM you own.
2. A Cisco DevNet sandbox you reserved.
3. A used IOS-XE box on your desk.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pip install 'pyats[full]'
cp testbeds/lab.yaml.example testbeds/lab.yaml
# edit IPs; export NCV_LAB_USER / NCV_LAB_PASS

ncv snapshot --testbed testbeds/lab.yaml --output captures/pre --i-am-in-a-lab
# in the lab: shut the peer link or remove a route
ncv snapshot --testbed testbeds/lab.yaml --output captures/post --i-am-in-a-lab
ncv diff captures/pre captures/post --intent intents/demo.yaml --report output/live
```

Promote into CI:

```bash
ncv snapshot --from-dir captures/pre --output fixtures/pre
ncv snapshot --from-dir captures/post --output fixtures/post
```

Hard rules: no passwords in git, no production, no default write path.
