# CLAUDE.md - batcontrol (simple rules fork)

Charges a Fronius GEN24 battery from the grid by three simple rules, using Tibber
15-minute prices. The rules and their parameters are described in `README.md`, which is
the only documentation. Python 3.11-3.14 (primary: 3.14).

## Commands

```bash
./run_tests.sh                                  # full suite + coverage (creates .venv via uv)
uv pip install -e '.[test]' pylint autopep8
uv run pytest tests/ -k <name>
uv run pylint src/batcontrol                    # target >= 9.0
python -m batcontrol --config PATH --one-shot   # one cycle, then exit
```

## Module map

```
src/batcontrol/
  rules.py          # THE logic: pure function plan(now, slots, battery, settings)
  core.py           # loop: read inverter + prices, rules.plan(), set mode; manual override
  tibber.py         # Tibber QUARTER_HOURLY prices -> rules.Slot list, cached
  inverter/         # Fronius GEN24 Solar API only (fronius.py) + resilient wrapper
  web/              # FastAPI: /api/v1/{health,status,manual-charge} + static dashboard
    static/         #   plain HTML/CSS/JS, no build step, no network access
  __main__.py       # CLI + 3-minute loop; core.wakeup cuts the sleep short
config/batcontrol_config_dummy.yaml   # every parameter; first-run template for Docker
tests/              # pytest, mirrors the package
scripts/build-and-push.sh  # podman build + push to 192.168.178.63:32768, tagged with the commit SHA
```

## Rules of the road

- Keep the logic in `rules.py` pure and simple. Every number the dashboard shows comes from
  a `rules.Plan`; the dashboard computes nothing of its own beyond formatting.
- Constants (4 kWh at midnight, 300 W, 16:00/08:00) are hardcoded on purpose. Ask before
  adding a config parameter; existing keys of older configs must keep loading (ignored keys
  are listed in `core.IGNORED_SECTIONS`).
- The web thread never talks to the inverter. It reads `Batcontrol.last` and may only
  request or cancel a manual charge, which sets `wakeup` for the loop.
- Timestamps in the API are epoch ms. Every numeric field in `web/models.py` carries its
  unit in the description (a test enforces this).
- ASCII only in Python source, including log messages.
- Nothing in `web/static/` may reference the network or use absolute paths (tested).
- New behaviour needs a pytest; a bug fix needs a regression test.
- Never commit `tmp/`, `.idea/` or `uv.lock`.
