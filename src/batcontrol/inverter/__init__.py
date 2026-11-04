""" Inverter backends. Only the Fronius GEN24 (Solar API) is supported. """
import logging

from .exceptions import (
    InverterError,
    InverterCommunicationError,
    InverterOutageError,
)
from .resilient_wrapper import (
    DEFAULT_OUTAGE_TOLERANCE_SECONDS,
    ResilientInverterWrapper,
)

logger = logging.getLogger(__name__)

SUPPORTED_TYPE = 'fronius_gen24'


def create_inverter(config: dict):
    """ Build the Fronius GEN24 backend from the `inverter:` config block. """
    if not isinstance(config, dict):
        raise RuntimeError('[Inverter] The inverter configuration must be a mapping')
    inverter_type = str(config.get('type', '')).lower()
    if inverter_type != SUPPORTED_TYPE:
        raise RuntimeError(
            f'[Inverter] Unsupported inverter type "{config.get("type")}". '
            f'Only "{SUPPORTED_TYPE}" is supported.')

    # Imported here so that tests and the web layer do not need requests
    # session setup at import time.
    from .fronius import FroniusWR  # pylint: disable=import-outside-toplevel

    max_grid_charge_rate = config.get('max_grid_charge_rate',
                                      config.get('max_charge_rate'))
    if max_grid_charge_rate is None:
        raise RuntimeError('[Inverter] max_grid_charge_rate is required')
    inverter = FroniusWR({
        'type': inverter_type,
        'address': config['address'],
        'user': config['user'],
        'password': config['password'],
        'max_grid_charge_rate': max_grid_charge_rate,
        'max_pv_charge_rate': config.get('max_pv_charge_rate', 0),
        'fronius_inverter_id': config.get('fronius_inverter_id', 1),
        'fronius_controller_id': config.get('fronius_controller_id', 0),
        'capacity': config.get('capacity', -1),
    })

    if not config.get('enable_resilient_wrapper', True):
        logger.info('Resilient wrapper disabled by configuration')
        return inverter
    tolerance = config.get('outage_tolerance_minutes',
                           DEFAULT_OUTAGE_TOLERANCE_SECONDS / 60) * 60
    return ResilientInverterWrapper(inverter, outage_tolerance_seconds=tolerance)


__all__ = [
    'create_inverter', 'InverterError', 'InverterCommunicationError',
    'InverterOutageError', 'ResilientInverterWrapper',
]
