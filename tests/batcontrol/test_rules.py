"""The three charging rules, with plain values."""
import datetime

import pytest
import pytz

from batcontrol import rules

TZ = pytz.timezone('Europe/Berlin')
SETTINGS = rules.Settings(max_charge_rate_w=3800)

# A typical autumn day: cheap at 03:00, a morning peak 07:00-08:00.
HOURLY = [0.24, 0.23, 0.22, 0.21, 0.21, 0.23, 0.30, 0.33, 0.31, 0.28, 0.25, 0.24,
          0.23, 0.23, 0.24, 0.26, 0.29, 0.34, 0.35, 0.33, 0.30, 0.28, 0.26, 0.25]
FLAT = [0.27] * 24


def at(day, hour, minute=0):
    return TZ.localize(datetime.datetime(2026, 11, day, hour, minute))


def slots(hourly=None, overrides=None, day=4, days=2):
    """15-min slots from midnight of `day`; overrides maps datetime -> price."""
    hourly = hourly or HOURLY
    overrides = overrides or {}
    start = at(day, 0)
    out = []
    for i in range(days * 96):
        when = TZ.normalize(start + datetime.timedelta(minutes=15 * i))
        out.append(rules.Slot(when, overrides.get(when, hourly[when.hour])))
    return out


def battery(soc, capacity=10000, min_soc=5, max_soc=100):
    return rules.Battery(soc=soc, capacity_wh=capacity, min_soc=min_soc, max_soc=max_soc)


# -- the reserve line ---------------------------------------------------------

@pytest.mark.parametrize('when, expected', [
    (at(4, 0), 4000),
    (at(4, 16), 6400),
    (at(4, 22), 4600),
    (at(4, 4), 2800),
    (at(4, 7, 30), 1750),
    (at(4, 12), 0),
])
def test_reserve_line(when, expected):
    assert rules.reserve_wh(when) == pytest.approx(expected)


def test_night_window_at_night_and_during_the_day():
    start, end, preview = rules.night_window(at(4, 22))
    assert (start, end, preview) == (at(4, 16), at(5, 8), False)
    start, end, preview = rules.night_window(at(5, 3))
    assert (start, end, preview) == (at(4, 16), at(5, 8), False)
    start, end, preview = rules.night_window(at(4, 12))
    assert (start, end, preview) == (at(4, 16), at(5, 8), True)


# -- rule 2: night reserve ----------------------------------------------------

def test_enough_energy_means_no_charge():
    plan = rules.plan(at(4, 22), slots(), battery(80), SETTINGS)
    assert plan.mode == rules.MODE_NORMAL
    assert plan.charges == ()
    assert plan.saving_eur == 0


def test_a_gap_is_bought_in_the_cheapest_slots_before_the_peak():
    # 40 % of 10 kWh minus 5 % min = 3.5 kWh usable; line at 22:00 is 4.6 kWh.
    plan = rules.plan(at(4, 22), slots(), battery(40), SETTINGS)
    assert plan.deficit_wh == pytest.approx(1100)
    assert plan.mode == rules.MODE_NORMAL          # not now, it is 26 ct
    (charge,) = plan.charges
    assert charge.reason == rules.REASON_NIGHT_RESERVE
    assert charge.start == at(5, 3)
    assert charge.energy_wh == pytest.approx(1100)
    assert charge.price == pytest.approx(0.21)
    assert charge.compare_price == pytest.approx(0.33)
    assert (charge.compare_start, charge.compare_end) == (at(5, 7), at(5, 8))
    # 1.1 kWh * 12 ct
    assert charge.saving_eur == pytest.approx(0.132)
    assert plan.saving_eur == pytest.approx(0.132)
    assert plan.monthly_saving_eur == pytest.approx(0.132 * 30)


def test_the_cheap_slot_charges_now_at_full_speed():
    plan = rules.plan(at(5, 3, 5), slots(), battery(20), SETTINGS)
    assert plan.mode == rules.MODE_CHARGE
    assert plan.reason == rules.REASON_NIGHT_RESERVE
    assert plan.charge_rate_w == 3800
    assert '07:00-08:00 costs 33.0 ct' in plan.headline


def test_a_large_gap_spreads_over_several_slots():
    # 5 % SoC at 22:00: 4.6 kWh missing, 950 Wh per slot -> 5 slots.
    plan = rules.plan(at(4, 22), slots(), battery(5), SETTINGS)
    energy = sum(c.energy_wh for c in plan.charges)
    assert energy == pytest.approx(4600)
    assert all(c.price <= 0.33 - 0.05 for c in plan.charges)


def test_no_charge_when_the_spread_is_below_five_cent():
    """Morning prices within 5 ct: nothing to save, so nothing is bought."""
    hourly = HOURLY[:]
    hourly[6] = hourly[7] = 0.25   # peak only 4 ct above the 21 ct night
    hourly[0:6] = [0.22] * 6
    plan = rules.plan(at(5, 1), slots(hourly), battery(10), SETTINGS)
    assert plan.charges == ()
    assert plan.mode == rules.MODE_NORMAL
    assert any('Not worth charging' in note for note in plan.notes)


def test_flat_prices_never_charge():
    plan = rules.plan(at(5, 1), slots(FLAT), battery(5), SETTINGS)
    assert plan.charges == ()


def test_a_custom_price_difference_is_respected():
    strict = rules.Settings(max_charge_rate_w=3800, min_price_difference=0.15)
    plan = rules.plan(at(4, 22), slots(), battery(40), strict)
    assert plan.charges == ()


def test_slots_after_the_last_peak_are_never_picked():
    """A charge must come before the hour it replaces."""
    plan = rules.plan(at(5, 7, 40), slots(), battery(5), SETTINGS)
    for charge in plan.charges:
        assert charge.compare_start >= charge.end


def test_a_small_gap_below_min_recharge_is_ignored():
    # Line at 22:00 is 4.6 kWh; 50 % -> 4.5 kWh usable -> 100 Wh short.
    plan = rules.plan(at(4, 22), slots(), battery(50), SETTINGS)
    assert plan.charges == ()
    assert any('minimum recharge' in note for note in plan.notes)


def test_a_running_charge_continues_below_min_recharge():
    plan = rules.plan(at(5, 3, 5), slots(), battery(31), SETTINGS,
                      was_charging=True)
    # Line at 03:05 is 3075 Wh; 31 % -> 2.6 kWh usable -> 475 Wh short.
    assert plan.mode == rules.MODE_CHARGE


def test_the_plan_never_exceeds_the_free_capacity():
    plan = rules.plan(at(4, 16), slots(), battery(10, capacity=4000, max_soc=50),
                      SETTINGS)
    assert sum(c.energy_wh for c in plan.charges) <= 1600 + 1e-6


def test_daytime_is_a_preview_and_tops_up_at_noon():
    # 30 % = 2.5 kWh usable, the 16:00 line is 6.4 kWh: 3.9 kWh short.
    plan = rules.plan(at(4, 10), slots(), battery(30), SETTINGS)
    assert plan.preview is True
    assert plan.mode == rules.MODE_NORMAL          # nothing before 12:00
    assert plan.reserve_wh == pytest.approx(6400)
    (charge,) = plan.charges
    assert charge.reason == rules.REASON_NIGHT_RESERVE
    assert (charge.start, charge.end) == (at(4, 12), at(4, 13, 15))
    assert charge.energy_wh == pytest.approx(3900)
    assert charge.price == pytest.approx(0.23)
    # Compared against the evening peak, which the night slots cannot cover.
    assert (charge.compare_start, charge.compare_end) == (at(4, 18), at(4, 19))


def test_the_day_top_up_charges_from_noon():
    plan = rules.plan(at(4, 12, 5), slots(), battery(30), SETTINGS)
    assert plan.mode == rules.MODE_CHARGE
    assert plan.reason == rules.REASON_NIGHT_RESERVE
    assert plan.charge_rate_w == 3800
    assert 'until 13:15' in plan.headline


def test_a_sunny_day_needs_no_top_up():
    plan = rules.plan(at(4, 12, 5), slots(), battery(80), SETTINGS)
    assert plan.mode == rules.MODE_NORMAL
    assert plan.charges == ()


def test_the_top_up_never_buys_before_noon():
    cheap = {at(4, 11, 45): 0.05}
    plan = rules.plan(at(4, 9), slots(overrides=cheap), battery(30), SETTINGS)
    assert all(c.start >= at(4, 12) for c in plan.charges)


def test_the_top_up_needs_the_price_difference_to_the_evening():
    # Midday as expensive as the evening: wait for the night instead.
    hourly = HOURLY[:12] + [0.33] * 4 + HOURLY[16:]
    plan = rules.plan(at(4, 12, 5), slots(hourly=hourly), battery(30), SETTINGS)
    assert plan.mode == rules.MODE_NORMAL
    assert plan.charges and all(c.start >= at(4, 16) for c in plan.charges)


def test_the_night_only_buys_what_the_day_did_not():
    # 10 %: 0.5 kWh usable, 5.9 kWh short. 12:00-16:00 is at least 9 ct
    # below the 35 ct evening peak and holds 16 x 950 Wh: all of it is
    # bought during the day, the night plan stays empty.
    plan = rules.plan(at(4, 11), slots(), battery(10), SETTINGS)
    assert sum(c.energy_wh for c in plan.charges) == pytest.approx(5900)
    assert all(c.end <= at(4, 16) for c in plan.charges)
    # With only 13:00-13:30 cheap enough, the rest goes to the night.
    hourly = HOURLY[:12] + [0.33] * 4 + HOURLY[16:]
    cheap = {at(4, 13): 0.20, at(4, 13, 15): 0.20}
    plan = rules.plan(at(4, 11), slots(hourly=hourly, overrides=cheap), battery(10), SETTINGS)
    day = [c for c in plan.charges if c.end <= at(4, 16)]
    night = [c for c in plan.charges if c.start >= at(4, 16)]
    assert sum(c.energy_wh for c in day) == pytest.approx(1900)
    assert sum(c.energy_wh for c in night) == pytest.approx(4000)


def test_missing_night_prices_are_reported():
    plan = rules.plan(at(4, 22), slots(days=1)[:88], battery(10), SETTINGS)
    assert 'No prices for the night yet.' in plan.notes


# -- rule 1: negative prices --------------------------------------------------

def test_a_negative_price_charges_at_full_speed_even_during_the_day():
    neg = {at(4, 13): -0.02, at(4, 13, 15): -0.03}
    plan = rules.plan(at(4, 13, 5), slots(overrides=neg), battery(60), SETTINGS)
    assert plan.mode == rules.MODE_CHARGE
    assert plan.reason == rules.REASON_NEGATIVE_PRICE
    assert plan.charge_rate_w == 3800
    first = plan.charges[0]
    assert first.reason == rules.REASON_NEGATIVE_PRICE
    assert (first.start, first.end) == (at(4, 13), at(4, 13, 30))
    assert first.saving_eur > 0
    assert 'negative' in plan.headline


def test_negative_energy_counts_against_the_night_gap():
    neg = {at(5, 2, 0): -0.01, at(5, 2, 15): -0.01}
    plan = rules.plan(at(4, 22), slots(overrides=neg), battery(40), SETTINGS)
    reserve = [c for c in plan.charges if c.reason == rules.REASON_NIGHT_RESERVE]
    negative = [c for c in plan.charges if c.reason == rules.REASON_NEGATIVE_PRICE]
    assert sum(c.energy_wh for c in negative) == pytest.approx(1900)  # 2 x 950
    assert reserve == []


def test_a_full_battery_still_lists_negative_slots_at_zero_energy():
    neg = {at(4, 13): -0.02}
    plan = rules.plan(at(4, 12), slots(overrides=neg), battery(100), SETTINGS)
    (charge,) = [c for c in plan.charges if c.reason == rules.REASON_NEGATIVE_PRICE]
    assert charge.energy_wh == 0


# -- rule 3: manual -----------------------------------------------------------

def test_manual_charge_wins():
    plan = rules.plan(at(4, 12), slots(), battery(90), SETTINGS,
                      manual_until=at(4, 13))
    assert plan.mode == rules.MODE_CHARGE
    assert plan.reason == rules.REASON_MANUAL
    assert '13:00' in plan.headline


def test_an_expired_manual_charge_is_ignored():
    plan = rules.plan(at(4, 12), slots(), battery(90), SETTINGS,
                      manual_until=at(4, 11))
    assert plan.mode == rules.MODE_NORMAL


# -- explanations ---------------------------------------------------------------

def test_explanations_are_ascii():
    neg = {at(5, 2): -0.01}
    plan = rules.plan(at(4, 22), slots(overrides=neg), battery(5), SETTINGS)
    texts = [plan.headline, *plan.notes, *(c.explanation for c in plan.charges)]
    for text in texts:
        text.encode('ascii')


def test_explanation_names_spread_and_peak():
    plan = rules.plan(at(4, 22), slots(), battery(40), SETTINGS)
    assert plan.charges[0].explanation == (
        'Charge 03:00-03:30 at 21.0 ct: 07:00-08:00 costs 33.0 ct (+12.0 ct).')
