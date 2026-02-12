# Sharding

Sharding splits nit's workload across parallel CI jobs for faster execution on large projects.

## How sharding works

1. Each CI job gets a `shard_index` (0-based) and `shard_count`
2. nit divides test generation targets across shards
3. Each shard processes its portion and writes a result JSON file
4. A final job downloads all shard results and combines them

## GitHub Actions matrix strategy

```yaml
name: nit (sharded)
on: push

permissions:
  contents: write
  pull-requests: write

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        shard: [0, 1, 2, 3]
    steps:
      - uses: actions/checkout@v4

      - uses: getnit-dev/nit@v1
        id: nit
        with:
          llm_provider: openai
          llm_api_key: ${{ secrets.OPENAI_API_KEY }}
          shard_index: ${{ matrix.shard }}
          shard_count: '4'

      # Shard results are automatically uploaded as artifacts

  combine:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Download shard results
        uses: actions/download-artifact@v4
        with:
          pattern: nit-shard-result-*
          path: .nit/

      - name: Install nit
        run: pip install getnit

      - name: Combine results
        run: nit combine --path .nit/ --output .nit/combined.json
```

## Local sharding

nit also supports automatic local sharding for projects with many test files:

```yaml
execution:
  parallel_shards: 4             # Number of parallel shards
  min_files_for_sharding: 8      # Minimum files to trigger sharding
```

When the number of test files exceeds `min_files_for_sharding`, nit automatically splits work across `parallel_shards` concurrent processes.

## CLI sharding

Run sharded from the command line:

```bash
# Shard 0 of 4
nit pick --shard-index 0 --shard-count 4 --shard-output .nit/shard-0.json

# Shard 1 of 4
nit pick --shard-index 1 --shard-count 4 --shard-output .nit/shard-1.json

# Combine all shards
nit combine --path .nit/ --output .nit/combined.json
```

## Shard result format

Each shard writes a JSON file containing:

```json
{
  "shard_index": 0,
  "shard_count": 4,
  "tests_generated": 12,
  "tests_passed": 11,
  "tests_failed": 1,
  "files_processed": ["src/auth.py", "src/api.py", "src/db.py"],
  "bugs_found": [],
  "errors": []
}
```

The `combine` command merges these into a single unified result.
