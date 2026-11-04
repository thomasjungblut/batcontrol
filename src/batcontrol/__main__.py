"""Command-line entry point for batcontrol."""

import argparse
import datetime
import logging
import signal
import sys

from .banner import log_startup_banner
from .core import Batcontrol
from .inverter import InverterOutageError
from .setup import setup_logging, load_config
from .web import config as web_config
from .web.server import WebServer


CONFIGFILE = "config/batcontrol_config.yaml"
EVALUATIONS_EVERY_MINUTES = 3  # Every x minutes on the clock
LOGFILE_ENABLED_DEFAULT = True
LOGFILE = "logs/batcontrol.log"


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog='batcontrol',
        description='Battery control system for dynamic tariff optimization'
    )
    parser.add_argument(
        '--one-shot',
        action='store_true',
        help='Run once and exit (load config, fetch data, run main loop once, then exit)'
    )
    parser.add_argument(
        '--config', '-c',
        default=CONFIGFILE,
        help=f'Path to configuration file (default: {CONFIGFILE})'
    )
    return parser.parse_args()


def main() -> int:
    # Parse command line arguments
    args = parse_arguments()

    # Configure a basic logger to be able to log even before the configuration is loaded
    setup_logging(level=logging.INFO)
    logger = logging.getLogger(__name__)
    logger.info('Looking for config file at %s', args.config)

    # Load the configuration
    config = load_config(args.config)

    # Load the config for the logger with the loaded configuration
    loglevel = config.get('loglevel', 'info')
    logfile_enabled = config.get('logfile_enabled', LOGFILE_ENABLED_DEFAULT)
    log_everything = config.get('log_everything', False)
    max_logfile_size = config.get('max_logfile_size', 200)  # Default 200KB
    logfile_path = config.get('logfile_path', LOGFILE)
    logfile = logfile_path if logfile_enabled else None

    if not logfile_enabled:
        logger.info("Logfile disabled in config. Proceeding without logfile")

    # Establish the loglevel mapping
    loglevel_mapping = {
        'debug': logging.DEBUG,
        'warning': logging.WARNING,
        'error': logging.ERROR,
        'info': logging.INFO
    }

    # Setup the logger based on the config
    setup_logging(
        level=loglevel_mapping.get(loglevel, logging.INFO),
        logfile=logfile,
        max_logfile_size_kb=max_logfile_size)
    logger = logging.getLogger(__name__)

    # Startup eyecatcher, emitted exactly once. Logged after the final logging
    # setup so that it also reaches the logfile.
    log_startup_banner()

    # Reduce the default loglevel for urllib3.connectionpool
    if not log_everything:
        logging.getLogger("websockets.protocol").setLevel(logging.WARNING)
        logging.getLogger("websockets.client").setLevel(logging.WARNING)
        logging.getLogger("asyncio").setLevel(logging.WARNING)
        logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)
        logging.getLogger("batcontrol.inverter.fronius.auth").setLevel(logging.INFO)

    bc = Batcontrol(config)

    api_config = web_config.from_config(config)
    web_server = None
    if api_config.enabled and not args.one_shot:
        web_server = WebServer(bc, api_config)
        if not web_server.start():
            web_server = None

    def _on_sigterm(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _on_sigterm)

    try:
        while True:
            bc.wakeup.clear()
            bc.run()

            # Exit after first run if --one-shot is specified
            if args.one_shot:
                logger.info("One-shot mode: exiting after single run")
                break

            loop_now = datetime.datetime.now().astimezone(bc.timezone)
            # reset base to full minutes on the clock
            next_eval = loop_now - datetime.timedelta(
                minutes=loop_now.minute % EVALUATIONS_EVERY_MINUTES,
                seconds=loop_now.second,
                microseconds=loop_now.microsecond
            )
            # add time increments to trigger next evaluation
            next_eval += datetime.timedelta(minutes=EVALUATIONS_EVERY_MINUTES)
            sleeptime = (next_eval - loop_now).total_seconds()
            bc.next_evaluation = next_eval.timestamp()
            logger.debug(
                "Next evaluation at %s. Sleeping for %d seconds",
                next_eval.strftime('%H:%M:%S'), int(sleeptime))
            # A manual charge from the dashboard wakes the loop up early.
            if bc.wakeup.wait(sleeptime):
                logger.info("Woken up early by a manual charge request")
    except KeyboardInterrupt:
        print("Shutting down")
    except InverterOutageError as e:
        logger.critical(
            "Inverter has been unreachable for too long. "
            "Terminating batcontrol. Error: %s", e
        )
        print(f"FATAL: Inverter outage exceeded tolerance - {e}")
        return 1
    finally:
        if web_server is not None:
            web_server.shutdown()
        bc.shutdown()
        del bc
    return 0


if __name__ == "__main__":
    sys.exit(main())
