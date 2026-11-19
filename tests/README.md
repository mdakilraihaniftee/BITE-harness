# Tests

`tests/parsec_vl/` covers the PARSEC-VL scheduler: DAG validation, E0/E1/E2
policies with measured interval overlap, resource capacities, budget safety under
concurrency, failure/timeout/cancellation handling, and the integration with the
real agent loop and multi-agent orchestrator. The rest of `tests/` covers the `openvlharness` package: configuration validation, the agent
loop, memory, model request formats, capabilities, the tool server and client,
the local tool backends and raw trace export. `tests/evaluation/` covers
`evaluation_kit`: run identity, resume and failed-row retries, per-example
records and reports, and benchmark scoring.

```bash
python -m pip install -e '.[test,server]'   # add eval for tests/evaluation
python -m pytest tests -q
```

`tests/evaluation/` is collected only when the `eval` extra is installed. The
tests run offline and need no GPU, model server or API key: `conftest.py` removes
provider credentials and proxy settings from the environment and refuses
connections to non-loopback addresses. [fixtures/README.md](fixtures/README.md)
describes the frozen reference outputs.
