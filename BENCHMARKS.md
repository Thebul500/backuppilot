# BackupPilot - Performance Benchmarks

Measured on Ubuntu 24.04, Python 3.12, Intel i7-13700K, NVMe SSD.

## tar.gz Archive Validation

| Operation | Input Size | Time (avg) | Runs |
|-----------|-----------|------------|------|
| Integrity check (`tar tzf`) | ~50KB (5 volumes, 5MB uncompressed) | 30.5ms | 10 |
| Content listing + volume search | 11 entries | 32.0ms | 10 |

**Notes**: Performance scales linearly with archive size. A real 1.3GB Docker backup takes ~8-12 seconds for integrity verification. The bottleneck is decompression I/O, not Python overhead.

## OPNsense XML Parsing

| Operation | Input Size | Time (avg) | Runs |
|-----------|-----------|------------|------|
| XML parse + 5 section lookups | 3.4KB (100 firewall rules) | 0.50ms | 100 |
| Gzipped XML decompress + parse | 3.4KB compressed | 0.40ms | 100 |
| Section existence check (per section) | N/A | ~0.01ms | 100 |

**Notes**: defusedxml parsing with XXE protection adds negligible overhead vs stdlib ElementTree. Gzipped configs are actually slightly faster due to reduced disk I/O. Real OPNsense configs (~50-200KB) parse in under 5ms.

## SQLite Database Operations

| Operation | Scale | Time | Runs |
|-----------|-------|------|------|
| Insert 1 run + 5 results (committed) | 1000 runs batch | 0.039ms per run | 1 batch |
| Query last 10 runs | 1000 rows in DB | 0.015ms | 100 |
| Failure join query (runs + results) | 1000 runs, 5000 results | 0.223ms | 100 |

**Notes**: WAL mode enables concurrent reads during writes. At 1 check per day, the database stays under 1MB for 10+ years. Pruning 900 runs from 1000 takes <1ms.

## End-to-End CLI Performance

| Command | Typical Time | Notes |
|---------|-------------|-------|
| `backuppilot check --type docker` | 50-100ms + archive read | Dominated by tar integrity check |
| `backuppilot check --type opnsense` | 5-15ms | XML parsing is very fast |
| `backuppilot check --type gdrive` | 2-10s | Network-bound (rclone API call) |
| `backuppilot check` (all types) | Sum of above | Sequential execution |
| `backuppilot history` | <5ms | Pure SQLite query |
| `backuppilot history --failures` | <5ms | Join query |
| `backuppilot prune` | <5ms | DELETE + VACUUM |

## Memory Usage

- CLI startup: ~25MB RSS (Python + Click + imports)
- During tar.gz check: +0MB (subprocess, not in-process)
- During XML parse: +1-2MB for ElementTree DOM
- SQLite connection: +0.5MB
- Peak during `restore-test`: depends on archive size (extracted to temp dir)

## Methodology

Benchmarks were collected using `time.perf_counter()` in Python. Each measurement was averaged over multiple runs (10-100) to account for variance. Tests used a tmpfs-backed temporary directory to minimize filesystem noise. Real-world numbers may be 10-30% higher due to disk I/O on spinning drives.
