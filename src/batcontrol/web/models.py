""" Response models of the web API.

Timestamps are epoch milliseconds, prices EUR/kWh, energy Wh, power W.
"""
from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar('T')


class Envelope(BaseModel, Generic[T]):
    """ Every successful response: {"ok": true, "data": ...}. """
    ok: bool = True
    data: T


class Health(BaseModel):
    """ Liveness. """
    status: str = Field(description="Always 'ok' while the server answers.")


class BatteryModel(BaseModel):
    """ The last inverter reading. """
    soc: float = Field(description='State of charge in percent.')
    stored_wh: float = Field(description='Energy in the battery in Wh.')
    usable_wh: float = Field(description='Energy above min_soc in Wh.')
    capacity_wh: float = Field(description='Gross capacity in Wh.')
    min_soc: float = Field(description='Lowest SoC the inverter allows, percent.')
    max_soc: float = Field(description='Highest SoC the inverter allows, percent.')


class ChargeModel(BaseModel):
    """ A planned block of grid charging. """
    reason: str = Field(description="'negative_price' or 'night_reserve'.")
    start: int = Field(description='Start, epoch ms.')
    end: int = Field(description='End, epoch ms.')
    price: float = Field(description='Average price while charging, EUR/kWh.')
    energy_wh: float = Field(description='Energy planned into the battery, Wh.')
    compare_price: float = Field(
        description='What the energy would cost otherwise, EUR/kWh: the '
                    'expensive hour it replaces, or the 24 h median.')
    compare_start: Optional[int] = Field(
        None, description='Start of the expensive hour, epoch ms.')
    compare_end: Optional[int] = Field(
        None, description='End of the expensive hour, epoch ms.')
    spread: float = Field(description='compare_price - price, EUR/kWh.')
    saving_eur: float = Field(description='Estimated saving of this block, EUR.')
    active: bool = Field(description='True while this block is running.')
    explanation: str = Field(description='One sentence why this block charges.')


class PlanModel(BaseModel):
    """ The rules' plan for the night. """
    night_start: int = Field(description='Start of the night window, epoch ms.')
    night_end: int = Field(description='End of the night window (08:00), epoch ms.')
    preview: bool = Field(
        description='True during the day: the coming night computed with '
                    "today's battery level, not executed yet.")
    reserve_wh: float = Field(description='Reserve line at now (or 16:00), Wh.')
    deficit_wh: float = Field(description='Reserve minus usable energy, Wh.')
    saving_eur: float = Field(
        description='Estimated saving of the charges in the next 24 h, EUR.')
    monthly_saving_eur: float = Field(
        description='saving_eur times 30, EUR.')
    charges: List[ChargeModel]
    notes: List[str] = Field(description='Why something was not done.')


class PriceSlotModel(BaseModel):
    """ One 15-minute price slot. """
    start: int = Field(description='Start, epoch ms.')
    price: float = Field(description='Total price, EUR/kWh.')
    charge: Optional[str] = Field(
        None, description='Reason if this slot is a planned charge.')


class StatusModel(BaseModel):  # pylint: disable=too-many-instance-attributes
    """ Everything the dashboard shows, from one control cycle. """
    version: str
    online: bool = Field(
        description='False when the control loop missed several evaluations.')
    evaluated_at: int = Field(description='Time of the evaluation, epoch ms.')
    next_evaluation: Optional[int] = Field(
        None, description='Next scheduled evaluation, epoch ms.')
    mode: str = Field(description="'charge' or 'normal'.")
    reason: str = Field(
        description="'negative_price', 'night_reserve', 'manual' or 'none'.")
    headline: str = Field(description='One sentence: what happens right now and why.')
    charge_rate_w: float = Field(description='Grid charge power in W, 0 if none.')
    max_charge_rate_w: float = Field(description='Configured full speed, W.')
    min_price_difference: float = Field(description='Required spread, EUR/kWh.')
    manual_until: Optional[int] = Field(
        None, description='End of a running manual charge, epoch ms.')
    battery: BatteryModel
    plan: PlanModel
    prices: List[PriceSlotModel] = Field(description='The next 24 h of prices.')


class ManualChargeRequest(BaseModel):
    """ Start a manual charge. """
    minutes: int = Field(60, ge=1, le=240,
                         description='Duration in minutes, 1-240. Default 60.')


class ManualChargeModel(BaseModel):
    """ State of the manual override. """
    active: bool
    until: Optional[int] = Field(None, description='End, epoch ms.')
