# Test Safety Rules

Some tests may touch real hardware, controllers, disks, firmware, networking, power state, or disruptive flows.

Before running tests that may affect hardware:

- Check the test name and fixture behavior.
- Avoid running broad suites if a focused test is enough.
- Do not run disruptive, destructive, power-cycle, firmware-upgrade, disk-wipe, RAID-rebuild, or real-DUT tests without explicit confirmation.
- Prefer dry-run, collection, static review, or narrow unit-level checks when available.

Safer checks:

```powershell
.\.venv\Scripts\python.exe -m pytest --collect-only
.\.venv\Scripts\python.exe -m pytest path\to\test_file.py --collect-only
```

After changes, run the narrowest useful verification first.

Examples:

```powershell
.\.venv\Scripts\python.exe -m pytest path\to\test_file.py --collect-only
.\.venv\Scripts\python.exe -m pytest path\to\test_file.py -k test_name
```

If tests cannot be run safely because they require real hardware or may be disruptive, state that clearly and provide the safest verification performed instead.
