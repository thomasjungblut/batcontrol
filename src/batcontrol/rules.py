""" The charging rules - a pure function from (time, prices, battery) to a plan.

There are exactly three reasons to charge the battery from the grid:

1. Negative price:   whenever a 15-minute slot costs less than 0, charge at
                     full speed. It lowers the average price and helps the grid.
2. Night reserve:    the battery has to bridge 16:00 to 08:00. The reserve line
                     is 4 kWh at midnight. Before midnight it is higher by
                     300 W per hour still to come (6.4 kWh at 16:00); after
                     midnight it falls by 300 W per hour (1.6 kWh at 08:00,
                     the buffer for the slow solar start). If the usable
                     energy is below the line, the gap is bought in the
                     cheapest slots before 08:00 - but only in slots that are
                     at least `min_price_difference` cheaper than the most
                     expensive hour still to come before 08:00. If no slot is
                     cheap enough, there is nothing to save and nothing is
                     bought: running out then costs the same.
3. Manual:           the dashboard button, full speed for a fixed time.

Outside of a charge the battery runs normally (house first, then battery,
then grid). Solar forecasts are not used at all.

Everything here is deterministic and side-effect free, so it can be tested
with plain values and shown 1:1 in the dashboard.
"""
import dataclasses
import datetime
import statistics
from typing import List, Optional, Sequence, Tuple

SLOT_MINUTES = 15
SLOT_HOURS = SLOT_MINUTES / 60
SLOT = datetime.timedelta(minutes=SLOT_MINUTES)

# The night the battery has to bridge, local time.
NIGHT_START_HOUR = 16
SOLAR_START_HOUR = 8
# Reserve line: energy needed at midnight and the night time draw.
MIDNIGHT_RESERVE_WH = 4000.0
NIGHT_LOAD_W = 300.0
# A slot counts as "the expensive hour" over this many slots.
PEAK_SLOTS = 4

DEFAULT_MIN_PRICE_DIFFERENCE = 0.05   # EUR/kWh
DEFAULT_MIN_RECHARGE_WH = 500.0

MODE_NORMAL = 'normal'
MODE_CHARGE = 'charge'

REASON_NEGATIVE_PRICE = 'negative_price'
REASON_NIGHT_RESERVE = 'night_reserve'
REASON_MANUAL = 'manual'
REASON_NONE = 'none'


@dataclasses.dataclass(frozen=True)
class Slot:
    """ One 15-minute price slot. `price` in EUR/kWh, `start` timezone aware. """
    start: datetime.datetime
    price: float

    @property
    def end(self) -> datetime.datetime:
        """ End of the slot. """
        return self.start + SLOT


@dataclasses.dataclass(frozen=True)
class Battery:
    """ What the inverter reports. SoC values in percent, energy in Wh. """
    soc: float
    capacity_wh: float
    min_soc: float
    max_soc: float

    @property
    def stored_wh(self) -> float:
        """ Energy in the battery. """
        return max(0.0, self.soc / 100 * self.capacity_wh)

    @property
    def usable_wh(self) -> float:
        """ Energy above the minimum SoC - what the house can actually use. """
        return max(0.0, (self.soc - self.min_soc) / 100 * self.capacity_wh)

    @property
    def free_wh(self) -> float:
        """ Room left up to the maximum SoC. """
        return max(0.0, (self.max_soc - self.soc) / 100 * self.capacity_wh)


@dataclasses.dataclass(frozen=True)
class Settings:
    """ The knobs. Read from the existing config keys, see core.py. """
    max_charge_rate_w: float
    min_price_difference: float = DEFAULT_MIN_PRICE_DIFFERENCE
    min_recharge_wh: float = DEFAULT_MIN_RECHARGE_WH

    @property
    def slot_energy_wh(self) -> float:
        """ What one slot of full speed charging puts into the battery. """
        return self.max_charge_rate_w * SLOT_HOURS


@dataclasses.dataclass(frozen=True)
class Charge:  # pylint: disable=too-many-instance-attributes
    """ A block of consecutive charge slots, for the plan and the dashboard.

    `price` is the average price of the block, `compare_price` what the
    energy would cost otherwise: the expensive hour it replaces (reserve) or
    the 24 h median (negative price). Savings in EUR.
    """
    reason: str
    start: datetime.datetime
    end: datetime.datetime
    price: float
    energy_wh: float
    compare_price: float
    compare_start: Optional[datetime.datetime]
    compare_end: Optional[datetime.datetime]
    saving_eur: float

    @property
    def spread(self) -> float:
        """ Price difference in EUR/kWh. """
        return self.compare_price - self.price

    @property
    def explanation(self) -> str:
        """ One sentence: why this block charges. ASCII only. """
        span = f'{hhmm(self.start)}-{hhmm(self.end)}'
        if self.reason == REASON_NEGATIVE_PRICE:
            return (f'Charge {span}: negative price {ct(self.price)} '
                    f'(typical {ct(self.compare_price)}).')
        return (f'Charge {span} at {ct(self.price)}: '
                f'{hhmm(self.compare_start)}-{hhmm(self.compare_end)} costs '
                f'{ct(self.compare_price)} (+{ct(self.spread)}).')


@dataclasses.dataclass(frozen=True)
class Plan:  # pylint: disable=too-many-instance-attributes
    """ The result of one evaluation.

    `mode`/`charge_rate_w` is what the inverter is told right now,
    `headline` the one-sentence explanation. `charges` lists what is planned
    from now on, `saving_eur` sums the charges of the next 24 hours.
    `preview` is set during the day: the night plan is then computed as if
    the night started now with today's battery level, and nothing in it is
    executed yet.
    """
    computed_at: datetime.datetime
    mode: str
    charge_rate_w: float
    reason: str
    headline: str
    charges: Tuple[Charge, ...]
    notes: Tuple[str, ...]
    night_start: datetime.datetime
    night_end: datetime.datetime
    preview: bool
    reserve_wh: float
    deficit_wh: float
    saving_eur: float

    @property
    def monthly_saving_eur(self) -> float:
        """ The cheap monthly estimate: one day times 30. """
        return self.saving_eur * 30


def ct(price: float) -> str:
    """ EUR/kWh as a 'ct' string for explanations. ASCII only. """
    return f'{price * 100:.1f} ct'


def hhmm(when: datetime.datetime) -> str:
    """ Local clock time. """
    return when.strftime('%H:%M')


def night_window(now: datetime.datetime) -> Tuple[datetime.datetime, datetime.datetime, bool]:
    """ The night that matters at `now`: (start, end, preview).

    At night that is the running night. During the day (08:00-16:00) it is the
    coming one, flagged as preview.
    """
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if now.hour >= NIGHT_START_HOUR:
        start = today.replace(hour=NIGHT_START_HOUR)
        end = (today + datetime.timedelta(days=1)).replace(hour=SOLAR_START_HOUR)
        return start, end, False
    if now.hour < SOLAR_START_HOUR:
        start = (today - datetime.timedelta(days=1)).replace(hour=NIGHT_START_HOUR)
        end = today.replace(hour=SOLAR_START_HOUR)
        return start, end, False
    start = today.replace(hour=NIGHT_START_HOUR)
    end = (today + datetime.timedelta(days=1)).replace(hour=SOLAR_START_HOUR)
    return start, end, True


def reserve_wh(when: datetime.datetime) -> float:
    """ The reserve line: usable energy needed at `when` to reach 08:00.

    4 kWh at midnight, +300 W for every hour before it, -300 W for every hour
    after it. Zero during the day.
    """
    hours = when.hour + when.minute / 60 + when.second / 3600
    if hours >= NIGHT_START_HOUR:
        return MIDNIGHT_RESERVE_WH + NIGHT_LOAD_W * (24 - hours)
    if hours < SOLAR_START_HOUR:
        return MIDNIGHT_RESERVE_WH - NIGHT_LOAD_W * hours
    return 0.0


def _peak_after(slots: Sequence[Slot], index: int) -> Optional[Tuple[float, int, int]]:
    """ The most expensive hour after slot `index`: (avg price, first, last).

    An hour is PEAK_SLOTS consecutive slots; with fewer left, the remaining
    slots form the window.
    """
    rest = range(index + 1, len(slots))
    if not rest:
        return None
    width = min(PEAK_SLOTS, len(rest))
    windows = [
        (sum(s.price for s in slots[first:first + width]) / width,
         first, first + width - 1)
        for first in range(index + 1, len(slots) - width + 1)
    ]
    # max() keeps the first of equal windows, i.e. the earliest hour.
    return max(windows, key=lambda w: w[0])


def _merge(reason: str, picked: List[Tuple[Slot, float, float, Optional[Tuple]]]) -> List[Charge]:
    """ Merge consecutive picked slots into blocks.

    `picked` holds (slot, energy, compare price, compare window) tuples.
    Slots are merged when they touch and compare against the same window.
    """
    picked = sorted(picked, key=lambda p: p[0].start)
    blocks: List[List] = []
    for item in picked:
        if blocks and blocks[-1][-1][0].end == item[0].start \
                and blocks[-1][-1][3] == item[3]:
            blocks[-1].append(item)
        else:
            blocks.append([item])
    charges = []
    for block in blocks:
        energy = sum(p[1] for p in block)
        cost = sum(p[0].price * p[1] for p in block)
        compare = sum(p[2] * p[1] for p in block)
        price = cost / energy if energy else block[0][0].price
        compare_price = compare / energy if energy else block[0][2]
        window = block[0][3]
        charges.append(Charge(
            reason=reason,
            start=block[0][0].start,
            end=block[-1][0].end,
            price=price,
            energy_wh=energy,
            compare_price=compare_price,
            compare_start=window[0] if window else None,
            compare_end=window[1] if window else None,
            saving_eur=(compare - cost) / 1000,
        ))
    return charges


def plan_negative(slots: Sequence[Slot], battery: Battery,
                  settings: Settings) -> List[Charge]:
    """ Every negative slot is a charge at full speed.

    The energy is estimated by filling the free capacity in order; the
    saving is measured against the median price of the known slots.
    """
    if not slots:
        return []
    median = statistics.median(s.price for s in slots[:96])
    room = battery.free_wh
    picked = []
    for slot in slots:
        if slot.price >= 0:
            continue
        energy = min(room, settings.slot_energy_wh)
        if energy <= 0:
            # Battery full: still listed, at zero energy, so the plan shows
            # that the slot was seen.
            energy = 0.0
        room -= energy
        picked.append((slot, energy, median, None))
    return _merge(REASON_NEGATIVE_PRICE, picked)


def plan_reserve(night: Sequence[Slot], deficit: float,  # pylint: disable=too-many-locals
                 settings: Settings) -> Tuple[List[Charge], Optional[str]]:
    """ Buy `deficit` Wh in the cheapest night slots worth it.

    A slot is worth it when it is at least min_price_difference cheaper than
    the most expensive hour after it, before 08:00. Returns the charges and,
    if the deficit could not be covered, a note why.
    """
    candidates = []
    for index, slot in enumerate(night):
        if slot.price < 0:
            continue  # already a negative price charge
        peak = _peak_after(night, index)
        if peak is None:
            continue
        if peak[0] - slot.price >= settings.min_price_difference:
            candidates.append((slot, peak))
    candidates.sort(key=lambda c: (c[0].price, c[0].start))

    picked = []
    remaining = deficit
    for slot, (peak_price, first, last) in candidates:
        if remaining <= 0:
            break
        energy = min(remaining, settings.slot_energy_wh)
        remaining -= energy
        window = (night[first].start, night[last].end)
        picked.append((slot, energy, peak_price, window))

    note = None
    if not candidates:
        cheapest = min(night, key=lambda s: s.price) if night else None
        if cheapest is not None:
            note = (f'Reserve short by {deficit / 1000:.1f} kWh, but no slot before '
                    f'{SOLAR_START_HOUR:02d}:00 is {ct(settings.min_price_difference)} '
                    f'cheaper than a later hour (cheapest {ct(cheapest.price)} at '
                    f'{hhmm(cheapest.start)}). Not worth charging from the grid.')
    elif remaining > 0:
        note = (f'Only {(deficit - remaining) / 1000:.1f} of {deficit / 1000:.1f} kWh '
                'fit into slots that are cheap enough.')
    return _merge(REASON_NIGHT_RESERVE, picked), note


def _headline(mode: str, reason: str, current: Optional[Charge],
              manual_until: Optional[datetime.datetime]) -> str:
    if reason == REASON_MANUAL and manual_until is not None:
        return f'Charging at full speed until {hhmm(manual_until)} (started by hand).'
    if mode == MODE_CHARGE and current is not None:
        if reason == REASON_NEGATIVE_PRICE:
            return (f'Charging until {hhmm(current.end)}: the price is negative '
                    f'({ct(current.price)}).')
        return (f'Charging until {hhmm(current.end)} at {ct(current.price)}, because '
                f'{hhmm(current.compare_start)}-{hhmm(current.compare_end)} costs '
                f'{ct(current.compare_price)} (+{ct(current.spread)}).')
    return 'Normal operation: solar to the house first, then the battery.'


def plan(now: datetime.datetime,  # pylint: disable=too-many-arguments,too-many-locals
         slots: Sequence[Slot],
         battery: Battery,
         settings: Settings,
         *,
         was_charging: bool = False,
         manual_until: Optional[datetime.datetime] = None) -> Plan:
    """ Evaluate the rules at `now`.

    Args:
        now: timezone aware local time.
        slots: price slots; past slots are ignored.
        battery: current reading.
        settings: rule parameters.
        was_charging: the last cycle charged for the reserve. Keeps a started
            charge going below min_recharge_wh instead of flapping.
        manual_until: end of a manual charge, if one is running.
    """
    slots = sorted((s for s in slots if s.end > now), key=lambda s: s.start)
    night_start, night_end, preview = night_window(now)
    notes: List[str] = []

    negative = plan_negative(slots, battery, settings)

    # The reserve is measured at the start of the night window during the
    # day (preview), otherwise right now.
    ref = night_start if preview else now
    reserve = reserve_wh(ref)
    deficit = max(0.0, reserve - battery.usable_wh)
    # Never plan beyond what fits into the battery.
    deficit = min(deficit, battery.free_wh)

    night = [s for s in slots if s.end > ref and s.start < night_end]
    negative_in_night = sum(c.energy_wh for c in negative
                            if night_start <= c.start < night_end)
    to_buy = max(0.0, deficit - negative_in_night)

    reserve_charges: List[Charge] = []
    if to_buy > 0 and (to_buy >= settings.min_recharge_wh or was_charging):
        reserve_charges, note = plan_reserve(night, to_buy, settings)
        if note:
            notes.append(note)
    elif to_buy > 0:
        notes.append(f'Reserve short by {to_buy:.0f} Wh, below the '
                     f'{settings.min_recharge_wh:.0f} Wh minimum recharge.')
    if not night:
        notes.append('No prices for the night yet.')

    charges = tuple(sorted(negative + reserve_charges, key=lambda c: c.start))

    # In a preview the reserve charges all start at 16:00 or later, so only
    # a negative price slot can be the current one during the day.
    current = next((c for c in charges if c.start <= now < c.end), None)

    if manual_until is not None and manual_until > now:
        mode, reason = MODE_CHARGE, REASON_MANUAL
    elif current is not None:
        mode, reason = MODE_CHARGE, current.reason
    else:
        mode, reason = MODE_NORMAL, REASON_NONE
        manual_until = None

    horizon = now + datetime.timedelta(hours=24)
    saving = sum(c.saving_eur for c in charges if c.start < horizon)

    return Plan(
        computed_at=now,
        mode=mode,
        charge_rate_w=settings.max_charge_rate_w if mode == MODE_CHARGE else 0.0,
        reason=reason,
        headline=_headline(mode, reason, current, manual_until),
        charges=charges,
        notes=tuple(notes),
        night_start=night_start,
        night_end=night_end,
        preview=preview,
        reserve_wh=reserve,
        deficit_wh=deficit,
        saving_eur=saving,
    )
