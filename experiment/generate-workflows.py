#!/usr/bin/env python3
"""Generate the six pipeline-configuration workflows from the templates.

The point of generating them is that the configurations then CANNOT differ in
anything except the factors that define them. Editing a generated workflow by
hand defeats that guarantee - edit the template instead and re-run this.

    python experiment/generate-workflows.py

Configurations (the independent variable, at six levels):

    A Full             no cache | lint | all tests, one process
    B Cached           CACHE    | lint | all tests, one process
    C Minimal          no cache | ---- | 1/4 of tests, one process
    D Cached+Minimal   CACHE    | ---- | 1/4 of tests, one process
    E Cached+Parallel  CACHE    | lint and test as parallel jobs (3 VMs)
    F Cached+Workers   CACHE    | lint | all tests, ACROSS THE RUNNER'S CORES

Ported from the ghostfolio fork (itself ported from hmpps). What is specific
to monize:

  * The test stage has two halves, measured as two labels: `test-unit`
    (CPU-bound, no database) and `test-integration` (one Postgres service).
    R3 is expected to go opposite ways on them. Their sum is the test stage.
  * "Minimal" shards BOTH halves with `--shard=1/4`.
  * `--forceExit` is on the unit half in all six configurations: in one
    process the unit suite passes and then never exits (open async handle).
  * F on the integration half needs one database per Jest worker (F'):
    experiment/patches/, applied in F only, between the unit and integration
    halves (the unit suite guards the upstream integration config).
"""

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
TPL = ROOT / "experiment" / "templates"
OUT = ROOT / ".github" / "workflows"

NO_CACHE = "          # NO `cache:` key. This is an UNCACHED configuration."
CACHE = (
    "          # Dependency caching ON - a defining factor of this configuration.\n"
    "          cache: 'npm'\n"
    "          cache-dependency-path: backend/package-lock.json"
)

# The test setting is set EXPLICITLY in every configuration and is never
# inherited from the subject application (EXPERIMENT-PLAN.md section 3).
# Jest is called directly rather than through the npm scripts, so the
# force-serial flag is written out here, not inherited from package.json.
#
#   one process - `--runInBand` on both halves. (The integration config also
#                 sets `maxWorkers: 1`; it agrees, and F's patch removes it.)
#   default     - `--runInBand` absent, so Jest picks its own worker count
#                 (cores - 1). Never a number chosen by hand.
UNIT = "npx jest --forceExit"
INT = r'npx jest --config ./test/jest-e2e.json --testPathPatterns="test/integration/.*\.spec\.ts$"'

SERIAL = " --runInBand"
SHARD = " --runInBand --shard=1/4"

NO_PATCH_STEP = ""

PATCH_STEP = """
      # Config F only, integration half: one database per Jest worker (F').
      # f.patch removes the force-serial settings (`--runInBand` in the npm
      # script, `maxWorkers: 1` in test/jest-e2e.json); fprime-db.patch gives
      # each worker its own database, named by JEST_WORKER_ID. Without it the
      # shared database fails 39 of 69 files in parallel.
      #
      # Applied AFTER the unit half, not before: the unit suite contains the
      # project's own guard (src/common/jest-config.guard.spec.ts) asserting
      # that the integration config is single-worker, so the unit half must see
      # the upstream config, exactly as in B. The patch is a millisecond
      # `git apply`, measured inside test-integration.
      - name: Apply Config F's integration change (one database per worker)
        run: |
          git apply experiment/patches/f.patch
          git apply experiment/patches/fprime-db.patch
          git status --short
"""

# `npm run lint` is the project's own lint script and includes `--fix`. A fix
# would change the source the later stages test and build, so the lint step
# fails the run if any file it lints has changed.
LINT_CMD = """|
          sum() { find src test -name '*.ts' -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum; }
          before="$(sum)"
          npm run lint
          [ "$(sum)" = "$before" ] || { echo "::error::lint --fix modified source files."; git status --short; exit 1; }"""

LINT_STEPS = f"""      - name: Lint
        working-directory: backend
        run: {LINT_CMD}

      - name: ECO-CI - measure lint
        uses: green-coding-solutions/eco-ci-energy-estimation@v5
        with:
          task: get-measurement
          label: lint
          send-data: false
"""

LINT_BLOCK = "\n      # ================= STAGE: LINT =================\n" + LINT_STEPS

# Config C and D remove the lint stage entirely; the comment keeps the removal
# visible in the generated file rather than leaving a silent gap.
NO_LINT_BLOCK = """
      # ================= STAGE: LINT - REMOVED =================
      # This is a MINIMAL configuration: the lint stage is not run. Lint emits
      # no files, so no later stage loses an input. What is given up is
      # detection, not build correctness.
"""

SINGLE = [
    # id, name, cache line, lint block, unit cmd, integration cmd, patch, rows
    ("A", "Full", NO_CACHE, LINT_BLOCK, UNIT + SERIAL, INT + SERIAL, NO_PATCH_STEP, 6),
    ("B", "Cached", CACHE, LINT_BLOCK, UNIT + SERIAL, INT + SERIAL, NO_PATCH_STEP, 6),
    ("C", "Minimal", NO_CACHE, NO_LINT_BLOCK, UNIT + SHARD, INT + SHARD, NO_PATCH_STEP, 5),
    ("D", "Cached+Minimal", CACHE, NO_LINT_BLOCK, UNIT + SHARD, INT + SHARD, NO_PATCH_STEP, 5),
    ("F", "Cached+Workers", CACHE, LINT_BLOCK, UNIT, INT, PATCH_STEP, 6),
]

POSTGRES_SERVICE = """    services:
      postgres:
        image: postgres:16-alpine@sha256:16bc17c64a573ef34162af9298258d1aec548232985b33ed7b1eac33ba35c229
        env:
          POSTGRES_DB: monize_test
          POSTGRES_USER: monize_test
          POSTGRES_PASSWORD: test_password
        ports: ['5432:5432']
        options: >-
          --health-cmd pg_isready --health-interval 10s --health-timeout 5s --health-retries 5
"""

TEST_STEPS = """      - name: Test - unit
        working-directory: backend
        run: |
          echo "+ $UNIT_CMD"
          eval "$UNIT_CMD"

      - name: ECO-CI - measure test-unit
        uses: green-coding-solutions/eco-ci-energy-estimation@v5
        with:
          task: get-measurement
          label: test-unit
          send-data: false

      - name: Test - integration
        working-directory: backend
        env:
          DATABASE_HOST: localhost
          DATABASE_PORT: 5432
          DATABASE_NAME: monize_test
          DATABASE_USER: monize_test
          DATABASE_PASSWORD: test_password
          JWT_SECRET: test-jwt-secret-for-ci-minimum-32-characters-long
          NODE_ENV: test
        run: |
          echo "+ $INT_CMD"
          eval "$INT_CMD"

      - name: ECO-CI - measure test-integration
        uses: green-coding-solutions/eco-ci-energy-estimation@v5
        with:
          task: get-measurement
          label: test-integration
          send-data: false
"""

BUILD_DEPLOY_STEPS = """      - name: Build
        working-directory: backend
        run: npm run build

      - name: ECO-CI - measure build
        uses: green-coding-solutions/eco-ci-energy-estimation@v5
        with:
          task: get-measurement
          label: build
          send-data: false

      - name: Deploy (package built app into image)
        run: docker build -f Dockerfile.experiment -t monize-backend:packaged .

      - name: ECO-CI - measure deploy
        uses: green-coding-solutions/eco-ci-energy-estimation@v5
        with:
          task: get-measurement
          label: deploy
          send-data: false
"""

# Config E: three jobs. lint and test run concurrently; build+deploy waits for
# both. Each job installs for itself because each is a fresh VM. The test job
# runs exactly B's commands.
PARALLEL_JOBS = [
    # id, name, needs, services, work, rows
    ("lint", "Lint (parallel with test)", "", "", LINT_STEPS, 2),
    ("test", "Test (parallel with lint)", "", POSTGRES_SERVICE, TEST_STEPS, 3),
    ("build", "Build and deploy", "    needs: [lint, test]\n", "", BUILD_DEPLOY_STEPS, 3),
]
E_UNIT, E_INT = UNIT + SERIAL, INT + SERIAL

HEADER = "# GENERATED FILE - do not edit. Regenerate with:\n#   python experiment/generate-workflows.py\n"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    single_tpl = (TPL / "single-job.yml.tpl").read_text(encoding="utf-8")

    for cid, name, cache, lint, unit_cmd, int_cmd, patch, rows in SINGLE:
        text = (
            single_tpl.replace("@@CONFIG@@", cid)
            .replace("@@CONFIG_NAME@@", name)
            .replace("@@CACHE_LINE@@", cache)
            .replace("@@CACHE_EXPECTED@@", "none" if cache is NO_CACHE else "hit")
            .replace("@@LINT_BLOCK@@", lint)
            .replace("@@PATCH_STEP@@", patch)
            .replace("@@UNIT_CMD@@", unit_cmd)
            .replace("@@INT_CMD@@", int_cmd)
            .replace("@@EXPECTED_ROWS@@", str(rows))
        )
        assert "@@" not in text, f"unfilled placeholder in config {cid}"
        path = OUT / f"config-{cid.lower()}.yml"
        path.write_text(HEADER + text, encoding="utf-8", newline="\n")
        print(f"wrote {path.relative_to(ROOT)}")

    head = (
        (TPL / "parallel-header.yml.tpl").read_text(encoding="utf-8")
        .replace("@@UNIT_CMD@@", E_UNIT)
        .replace("@@INT_CMD@@", E_INT)
    )
    job_tpl = (TPL / "parallel-job.yml.tpl").read_text(encoding="utf-8")
    parts = []
    for job_id, job_name, needs, services, work, rows in PARALLEL_JOBS:
        parts.append(
            job_tpl.replace("@@JOB_ID@@", job_id)
            .replace("@@JOB_NAME@@", job_name)
            .replace("@@NEEDS@@", needs)
            .replace("@@SERVICES@@", services)
            .replace("@@CACHE_EXPECTED@@", "hit")   # every Config E job is cached
            .replace("@@WORK@@", work)
            .replace("@@EXPECTED_ROWS@@", str(rows))
        )
    # The header ends with "jobs:"; jobs are separated by one blank line.
    text = head + "\n".join(parts)
    assert "@@" not in text, "unfilled placeholder in config E"
    path = OUT / "config-e.yml"
    path.write_text(HEADER + text, encoding="utf-8", newline="\n")
    print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
