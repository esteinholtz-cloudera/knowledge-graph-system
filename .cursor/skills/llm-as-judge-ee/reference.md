# EE Evaluation Reference

Reference patterns from a calibrated technical-doc run (Qwen3-30B, `ZDU_prereqs.txt`). Use as examples when writing reports — not as hardcoded prompt defaults.

## Reference metrics (ZDU run)

| Metric | Value |
|--------|-------|
| Unique entities | 144 |
| Marked spans | 335 |
| Orphan rate | ~19% (27/144) |
| Questionable extractions | ~22% |
| Grade | B− / usable but noisy |

## Type misclassification examples

| Entity | Assigned | Should be |
|--------|----------|-----------|
| `Configuring high availability for Hue` | Event | Document |
| `Zero Downtime Upgrade (ZDU)` | Event | Concept |
| `1,800,000 ms` | Date | Configuration |
| `yum install gcc openssl-devel...` | Technology | exclude (command) |
| `Atlas Hook` | Technology | `ATLAS_HOOK` verbatim |
| `Hdfs`, `Yarn` | Technology | Product/Service — preserve `HDFS`, `YARN` |

## Generic phrase false positives

`restart`, `Restart`, `topic`, `read-only`, `1 follower replica`, `leader replica`, `external clients`, `source cluster`, `retryParams`, `clientConfig`

## Version fragmentation

**Bad:** `7.1.7`, `7.1.7 Sp2`, `Cloudera Runtime` separate from `7.1.7 SP3`

**Missing:** `CDP 7.1.8 cumulative hotfix 17`, `replication.factor`, `ATLAS_HOOK`

**Good pattern:** extract full span as Product + version substring as Version

## Redundancy clusters

```
ZDU, Zero Downtime Upgrade, Zero Downtime Upgrade (ZDU), ZDU process, ZDU implementation
High Availability, HA mode, High Availability mode, ResourceManager HA
Cloudera Runtime, Cloudera Runtime 7.1.9
```

## Model-tier guidance

| Tier | Typical settings |
|------|------------------|
| Strong instruction followers (Qwen3-30B, GPT-4) | `format_strictness: low`, few-shot optional |
| Mid-tier (~28B) | `format_strictness: medium`, `use_few_shot: true`, smaller chunks |
| Weak/small | `format_strictness: high`, few-shot required, smaller `chunk_size` |

## Neutral few-shot pattern (generic)

Use domain-appropriate names, not Cloudera-specific strings, when adding structure-layer examples:

```
Example input: "Acme Platform 2.1.0 requires setting cache.size to at least 1024."
Example output:
[
  {"entity": "Acme Platform 2.1.0", "type": "Product", "context": "minimum version requirement"},
  {"entity": "2.1.0", "type": "Version", "context": "platform version"},
  {"entity": "cache.size", "type": "Configuration", "context": "required setting"}
]
```
