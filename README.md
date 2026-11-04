# batcontrol (simple rules)

A stripped-down fork of [batcontrol](https://github.com/MaStr/batcontrol) for one setup:
a **Fronius GEN24** with battery (Solar API), **Tibber** 15-minute prices, about 15 kWh
consumption a day and a 10 kWh battery. No solar or consumption forecasts: fog makes
them wrong too often.

## The rules

The house always takes solar first, then the battery, then the grid. batcontrol only
decides when to **charge from the grid**. There are three reasons to do so:

1. **Negative price.** Any 15-minute slot below 0 ct charges at full speed
   (`max_grid_charge_rate`), day or night. It lowers the average price and helps the grid.
2. **Night reserve.** The battery has to get the house through 16:00 to 08:00. The reserve
   line is **4 kWh at midnight**, plus 300 W for every hour before midnight
   (6.4 kWh at 16:00) and minus 300 W for every hour after it (1.6 kWh at 08:00, which
   covers the slow solar start). If the usable energy (above the minimum SoC) is below the
   line, the shortfall is bought in the **cheapest slots before 08:00**. A slot only
   qualifies if it is at least `min_price_difference` (5 ct) cheaper than the most
   expensive hour still to come before 08:00. If no slot is cheap enough, nothing is
   bought, because running out would cost the same.
3. **Manual.** The dashboard button charges at full speed for one hour.

Everything is re-evaluated every 3 minutes. Shortfalls smaller than
`min_recharge_amount` (500 Wh) are ignored, but a charge that has already started runs on
until the gap is closed.

**Savings** are estimated per charge block as energy × (price of the expensive hour it
replaces − charge price). For negative prices the comparison is the 24-hour median. The
dashboard adds them up for the next 24 hours and multiplies by 30 for a rough monthly figure.

During the day (08:00 to 16:00) the plan for the coming night is shown as a **preview**,
computed with the current battery level. It is not acted on until 16:00.

## Configuration

See [`config/batcontrol_config_dummy.yaml`](config/batcontrol_config_dummy.yaml). An
existing batcontrol config keeps working, and keys the rules don't use are ignored (and
logged once at startup).

## Run

```bash
docker compose up -d --build      # see compose.yaml: ./config and ./logs as volumes
# or from source
uv venv --python 3.14 && uv pip install -e '.[test]'
python -m batcontrol --config config/batcontrol_config.yaml [--one-shot]
```

To build with podman and push to the local registry (tagged with the short commit SHA
and `latest`; `NO_PUSH=1` builds only):

```bash
scripts/build-and-push.sh
```

The image is `python:3.14-slim` (Debian). On first start with an empty `./config` it
copies a template config and exits; fill it in and start again. Set `TZ` in
`compose.yaml` and make the published port match `api.port`. `docker stop` sends
SIGTERM, batcontrol then restores the inverter settings it changed (from the backup
files in `./config`) before it exits.

The dashboard is at `http://<host>:<api.port>/`. It is plain HTML/CSS/JS in
`src/batcontrol/web/static/`, with no build step.

## API

All under `/api/v1/`. Timestamps are epoch ms, prices EUR/kWh, energy Wh, power W.

| Method | Path | |
|---|---|---|
| GET | `/health` | always open, for health checks |
| GET | `/status` | battery, mode and reason, the plan with savings, 24 h of prices |
| GET | `/manual-charge` | whether a manual charge is running |
| POST | `/manual-charge` | `{"minutes": 60}` (1–240), charge at full speed |
| DELETE | `/manual-charge` | stop it |

Set `api.auth_token` to require `Authorization: Bearer <token>` on everything except
`/health`. Without a token, anyone on your network can start a manual charge.

## Tests

```bash
./run_tests.sh
uv run pylint src/batcontrol
```
