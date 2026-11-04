""" Routes of the web API.

GET /health and /status read the last control cycle; nothing here talks to
the inverter. The only write is the manual charge, which just records the
request and wakes the control loop up - the loop then sets the mode.
"""
import datetime
import time
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .. import __pkginfo__
from .. import rules
from .models import (
    BatteryModel, ChargeModel, Envelope, Health, ManualChargeModel,
    ManualChargeRequest, PlanModel, PriceSlotModel, StatusModel,
)

# The loop evaluates every 3 minutes; three missed cycles mean "offline".
OFFLINE_AFTER_SECONDS = 10 * 60
PRICE_HORIZON = datetime.timedelta(hours=24)

public_router = APIRouter()
router = APIRouter()


class NoDataAvailable(Exception):
    """ Raised before the first control cycle has finished. """


def error_envelope(code: str, detail: str) -> dict:
    """ Body of every error response. """
    return {'ok': False, 'error': code, 'detail': detail}


def no_data_response() -> JSONResponse:
    """ 503 before the first cycle. """
    return JSONResponse(status_code=503, content=error_envelope(
        'no_data', 'batcontrol has not completed a control cycle yet.'))


def ms(when) -> Optional[int]:
    """ datetime or epoch seconds to epoch ms. """
    if when is None:
        return None
    if isinstance(when, datetime.datetime):
        return int(when.timestamp() * 1000)
    return int(when * 1000)


def _charge(charge: rules.Charge, now: datetime.datetime) -> ChargeModel:
    return ChargeModel(
        reason=charge.reason,
        start=ms(charge.start),
        end=ms(charge.end),
        price=round(charge.price, 4),
        energy_wh=round(charge.energy_wh, 1),
        compare_price=round(charge.compare_price, 4),
        compare_start=ms(charge.compare_start),
        compare_end=ms(charge.compare_end),
        spread=round(charge.spread, 4),
        saving_eur=round(charge.saving_eur, 3),
        active=charge.start <= now < charge.end,
        explanation=charge.explanation,
    )


def _charge_reason(slot: rules.Slot, plan: rules.Plan) -> Optional[str]:
    for charge in plan.charges:
        if charge.start <= slot.start < charge.end:
            return charge.reason
    return None


def build_status(bc) -> StatusModel:
    """ The status view of the last cycle. """
    result = bc.last
    if result is None:
        raise NoDataAvailable()
    plan = result.plan
    battery = result.battery
    now = plan.computed_at
    manual = bc.manual_until
    return StatusModel(
        version=__pkginfo__.__version__,
        online=time.time() - result.evaluated_at < OFFLINE_AFTER_SECONDS,
        evaluated_at=ms(result.evaluated_at),
        next_evaluation=ms(bc.next_evaluation),
        mode=plan.mode,
        reason=plan.reason,
        headline=plan.headline,
        charge_rate_w=plan.charge_rate_w,
        max_charge_rate_w=bc.settings.max_charge_rate_w,
        min_price_difference=bc.settings.min_price_difference,
        manual_until=ms(manual),
        battery=BatteryModel(
            soc=battery.soc,
            stored_wh=round(battery.stored_wh, 1),
            usable_wh=round(battery.usable_wh, 1),
            capacity_wh=battery.capacity_wh,
            min_soc=battery.min_soc,
            max_soc=battery.max_soc,
        ),
        plan=PlanModel(
            night_start=ms(plan.night_start),
            night_end=ms(plan.night_end),
            preview=plan.preview,
            reserve_wh=round(plan.reserve_wh, 1),
            deficit_wh=round(plan.deficit_wh, 1),
            saving_eur=round(plan.saving_eur, 3),
            monthly_saving_eur=round(plan.monthly_saving_eur, 2),
            charges=[_charge(c, now) for c in plan.charges],
            notes=list(plan.notes),
        ),
        prices=[
            PriceSlotModel(start=ms(s.start), price=round(s.price, 4),
                           charge=_charge_reason(s, plan))
            for s in result.slots if s.start < now + PRICE_HORIZON
        ],
    )


def _manual(bc) -> ManualChargeModel:
    until = bc.manual_until
    return ManualChargeModel(active=until is not None, until=ms(until))


@public_router.get('/health', response_model=Envelope[Health])
def health():
    """ Liveness check, never needs a token. """
    return Envelope(data=Health(status='ok'))


@router.get('/status', response_model=Envelope[StatusModel])
def status(request: Request):
    """ Battery, current mode with its reason, the plan and the prices. """
    return Envelope(data=build_status(request.app.state.batcontrol))


@router.get('/manual-charge', response_model=Envelope[ManualChargeModel])
def manual_state(request: Request):
    """ Whether a manual charge is running. """
    return Envelope(data=_manual(request.app.state.batcontrol))


@router.post('/manual-charge', response_model=Envelope[ManualChargeModel])
def manual_start(request: Request, body: Optional[ManualChargeRequest] = None):
    """ Charge at full speed for `minutes` (default 60). """
    bc = request.app.state.batcontrol
    bc.start_manual_charge((body or ManualChargeRequest()).minutes)
    return Envelope(data=_manual(bc))


@router.delete('/manual-charge', response_model=Envelope[ManualChargeModel])
def manual_cancel(request: Request):
    """ Stop a manual charge; the rules take over again. """
    bc = request.app.state.batcontrol
    bc.cancel_manual_charge()
    return Envelope(data=_manual(bc))
