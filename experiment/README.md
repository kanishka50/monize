# Green DevOps measurement harness (subject 3: monize backend)

Added to a fork of `kenlasko/monize` for the research project _Towards Green
DevOps: Measuring and Optimising the Resource Consumption and Environmental
Impact of CI/CD Pipelines_ (Kanishka, University of Kelaniya).

**The upstream application is not modified in the repository.** Everything
added lives in `experiment/`, `.github/workflows/config-*.yml`,
`.github/workflows/cache-warmup.yml`, `Dockerfile.experiment` and
`Dockerfile.experiment.dockerignore`. Each run verifies that `backend/` and
`database/` still match upstream commit
`d162a2859f31114986c66d50e7605c0221ca85b3`, and fails if they do not.

Ported from the ghostfolio fork (itself ported from hmpps).

## The six configurations

| Config            | Cache | Lint | Tests (unit and integration halves)        | Machines |
| ----------------- | ----- | ---- | ------------------------------------------ | -------- |
| A Full            | no    | yes  | all, one process                           | 1        |
| B Cached          | yes   | yes  | all, one process                           | 1        |
| C Minimal         | no    | no   | `--shard=1/4` of both halves, one process  | 1        |
| D Cached+Minimal  | yes   | no   | `--shard=1/4` of both halves, one process  | 1        |
| E Cached+Parallel | yes   | yes  | all; lint and test on separate machines    | 3        |
| F Cached+Workers  | yes   | yes  | all, Jest's own default worker count       | 1        |

Declared changes to the subject:

- `--forceExit` on the unit half in **all six**: run in one process, the unit
  suite passes and then never exits (an open async handle).
- **F only, integration half:** one database per Jest worker
  (`experiment/patches/f.patch` + `fprime-db.patch`, applied before measuring).
  Without it the shared database fails 39 of 69 files in parallel.

The test stage is measured as two labels, `test-unit` and `test-integration`;
their sum is the test stage. `analyse.py` (copied from ghostfolio) still
expects a single `test` label and must be adapted before Stage 9 analysis.

## Running it

```bash
python experiment/generate-workflows.py          # after editing a template
gh workflow run cache-warmup.yml --repo kanishka50/monize   # once; again after 7 days unused
bash experiment/run-pilot.sh 10 <seed>           # 60 runs, serial, seeded
bash experiment/collect-results.sh               # download + combine
```

Nothing is published to npm, pushed to a registry, or sent to ECO-CI's servers
(`send-data: false` on every measurement).
