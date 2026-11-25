"""Third-party loggers that echo document text at DEBUG level.

Found by tests/test_security.py: presidio-analyzer logs analysed text and matched values at
DEBUG. Pinning these loggers to WARNING means turning on debug logging for our own code can
never route raw identifiers into log files. The pin is a logger *level*, so it holds even when
the root logger is set to DEBUG.
"""

from __future__ import annotations

import logging

LEAKY_LOGGERS = ("presidio-analyzer", "presidio-anonymizer", "presidio_analyzer", "presidio_anonymizer")


def silence_leaky_loggers() -> None:
    for name in LEAKY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
