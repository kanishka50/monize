  @@JOB_ID@@:
    name: E - @@JOB_NAME@@
    runs-on: ubuntu-latest
    timeout-minutes: 75
@@NEEDS@@@@SERVICES@@
    steps:
      - name: Log runner context
        run: |
          echo "RUN_STARTED=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$GITHUB_ENV"
          echo "=== RUNNER CONTEXT (control variables) ==="
          echo "Config:   E   Job: @@JOB_ID@@"
          echo "Image:    ${ImageOS:-unknown} / ${ImageVersion:-unknown}"
          echo "CPU:      $(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2- | xargs)"
          echo "Cores:    $(nproc)"

      - name: Clone repository
        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false

      - name: Verify the measured workload is the pinned one
        run: |
          BACKEND_TREE="$(git rev-parse HEAD:backend)"
          DATABASE_TREE="$(git rev-parse HEAD:database)"
          fail=0
          [ "$BACKEND_TREE"  = "${{ env.SUBJECT_BACKEND_TREE }}" ]  || { echo "::error::backend/ tree differs from the pinned workload."; fail=1; }
          [ "$DATABASE_TREE" = "${{ env.SUBJECT_DATABASE_TREE }}" ] || { echo "::error::database/ tree differs from the pinned workload."; fail=1; }
          if [ "$fail" = "1" ]; then exit 1; fi
          echo "Workload matches the pinned upstream source."

      - name: Set up Node.js
        id: setup
        uses: actions/setup-node@820762786026740c76f36085b0efc47a31fe5020 # v7.0.0
        with:
          node-version: '24.20.0'
          # Config E is a CACHED configuration; every job restores the cache.
          cache: 'npm'
          cache-dependency-path: backend/package-lock.json

      # A CACHED configuration whose cache did not actually restore has silently
      # run as an UNCACHED one, so the run fails here instead (see single-job
      # template and cache-warmup.yml).
      - name: Verify the cache state matches the configuration
        run: |
          expected='@@CACHE_EXPECTED@@'
          actual='${{ steps.setup.outputs.cache-hit }}'
          echo "cache expected: $expected | setup-node reported: '${actual:-<none>}'"
          if [ "$expected" = "hit" ] && [ "$actual" != "true" ]; then
            echo "::error::CACHED configuration did not restore a cache. This run would"
            echo "::error::have measured an uncached install. Discarding it."
            echo "::error::Run the 'Cache warm-up (not measured)' workflow, then re-dispatch."
            exit 1
          fi
          if [ "$expected" = "none" ] && [ "$actual" = "true" ]; then
            echo "::error::UNCACHED configuration restored a cache. Not a valid measurement."
            exit 1
          fi

      - name: ECO-CI - start measurement
        uses: green-coding-solutions/eco-ci-energy-estimation@v5
        with:
          task: start-measurement
          send-data: false
          json-output: true

      # Each job runs on its own VM and therefore installs for itself. This
      # install is part of the configuration's real cost and is measured.
      - name: Install dependencies
        working-directory: backend
        run: npm ci

      - name: ECO-CI - measure install
        uses: green-coding-solutions/eco-ci-energy-estimation@v5
        with:
          task: get-measurement
          label: install
          send-data: false

@@WORK@@
      - name: ECO-CI - display results
        uses: green-coding-solutions/eco-ci-energy-estimation@v5
        with:
          task: display-results
          send-data: false

      - name: Write result files
        if: always()
        run: |
          mkdir -p results
          cp -r /tmp/eco-ci results/eco-ci-raw 2>/dev/null \
            || echo "WARNING: /tmp/eco-ci not present"

          CPU="$(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2- | xargs)"
          jq -n \
            --arg job '@@JOB_ID@@' \
            --arg run_id '${{ github.run_id }}' --arg run_number '${{ github.run_number }}' \
            --arg run_attempt '${{ github.run_attempt }}' \
            --arg commit "$(git rev-parse HEAD)" --arg backend_tree "$(git rev-parse HEAD:backend)" \
            --arg unit_cmd "$UNIT_CMD" --arg int_cmd "$INT_CMD" \
            --arg image "${ImageOS:-unknown}/${ImageVersion:-unknown}" \
            --arg cpu "$CPU" --arg cores "$(nproc)" \
            --arg started '${{ env.RUN_STARTED }}' --arg finished "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
            '{config: "E", config_name: "Cached+Parallel", subject: "monize-backend", job: $job,
              run_id: $run_id, run_number: $run_number, run_attempt: $run_attempt,
              commit: $commit, backend_tree: $backend_tree, unit_cmd: $unit_cmd, int_cmd: $int_cmd,
              runner_image: $image, cpu_model: $cpu, cpu_cores: $cores,
              eco_power_model: "github_EPYC_7763_4_CPU_shared.sh",
              started_utc: $started, finished_utc: $finished}' > results/meta.json

          VARS=results/eco-ci-raw/vars.sh
          getvar() {
            grep -m1 -E "^(export[[:space:]]+)?$1=" "$VARS" 2>/dev/null \
              | sed -E "s/^(export[[:space:]]+)?$1=//" \
              | sed -E "s/^[\"']//; s/[\"']$//"
          }

          echo "config,job,run_id,run_number,cpu_model,stage_index,label,cpu_avg_pct,energy_j,power_avg_w,duration_s" > results/measurements.csv
          i=1
          while [ -n "$(getvar "ECO_CI_MEASUREMENT_${i}_LABEL")" ]; do
            printf '%s,%s,%s,%s,"%s",%s,%s,%s,%s,%s,%s\n' \
              "E" "@@JOB_ID@@" \
              "${{ github.run_id }}" "${{ github.run_number }}" "$CPU" "$i" \
              "$(getvar "ECO_CI_MEASUREMENT_${i}_LABEL")" \
              "$(getvar "ECO_CI_MEASUREMENT_${i}_CPU_AVG")" \
              "$(getvar "ECO_CI_MEASUREMENT_${i}_ENERGY")" \
              "$(getvar "ECO_CI_MEASUREMENT_${i}_POWER_AVG")" \
              "$(getvar "ECO_CI_MEASUREMENT_${i}_TIME")" \
              >> results/measurements.csv
            i=$((i + 1))
          done
          cat results/measurements.csv

          rows=$(( $(wc -l < results/measurements.csv) - 1 ))
          if [ "$rows" -lt @@EXPECTED_ROWS@@ ]; then
            echo "::error::Parsed $rows measurement rows in job @@JOB_ID@@, expected @@EXPECTED_ROWS@@."
            exit 1
          fi

          case "$CPU" in
            *7763*) echo "Power model MATCHES runner CPU ($CPU)." ;;
            *) echo "::warning::Runner CPU is '$CPU' but ECO-CI estimates with the EPYC 7763 power model." ;;
          esac

      - name: Upload results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: result-E-@@JOB_ID@@-${{ github.run_id }}-${{ github.run_attempt }}
          path: results/
          retention-days: 30
          if-no-files-found: error
