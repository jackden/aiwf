# Storage Safety Rules

When implementing disk cleanup or destructive storage operations:

1. Separate target devices from observed system sources.
   - Target devices are user/framework-selected cleanup targets, e.g. `/dev/sdb`.
   - Observed sources are OS-reported paths from `/proc/mounts`, `/proc/swaps`, `lsblk`, or `mdstat`, e.g. `/dev/mapper/openeuler-root`.
   - Do not pass observed sources directly into strict target-device validators.

2. Strict target validators must only validate devices intended for destructive operations.
   - Example: `_normalize_block_device`, `_assert_whole_disk_device`.
   - These must not be used blindly on mount sources, swap sources, LVM mapper paths, or dm devices.

3. For system disk protection, resolve backing disks before comparing.
   - `/dev/mapper/*` and LVM paths must be resolved with `lsblk -s` or equivalent.
   - Compare cleanup target against backing whole disks, not against the raw mount source string.

4. Safety checks must handle at least these protected source forms:
   - `/dev/sda1` mounted as `/`
   - `/dev/mapper/<vg>-root` mounted as `/`
   - `/dev/mapper/<vg>-swap` active as swap
   - `/dev/nvme0n1pX` mounted as `/`
   - unresolved `/dev/*` source must fail closed, not continue silently.

5. Unit tests for destructive disk cleanup must not mock away the safety function under change.
   - If `_assert_not_system_disk` is changed, tests must exercise real behavior with fake command outputs.
   - Include both allowed and rejected cases.

6. Prefer fail-closed behavior only after correct source resolution.
   - It is acceptable to reject cleanup when backing disk cannot be resolved.
   - It is not acceptable to assert early because a valid OS source path has a different form than cleanup targets.
