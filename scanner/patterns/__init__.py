"""Pattern detection package."""

from __future__ import annotations

import logging
import pandas as pd

from .base import Pattern  # noqa: F401  (re-export for callers)

logger = logging.getLogger(__name__)


def detect_all_patterns(df: pd.DataFrame) -> list[Pattern]:
    """Run all detectors and return combined pattern list."""
    from .reversal      import detect_reversal_patterns
    from .continuation  import detect_continuation_patterns
    from .breakout      import detect_breakout_patterns
    from .triangles     import detect_triangle_patterns
    from .ma_patterns   import detect_ma_patterns
    from .divergence    import detect_divergence_patterns
    from .candlestick   import detect_candlestick_patterns
    from .wyckoff       import detect_wyckoff_patterns

    detectors = [
        detect_reversal_patterns,
        detect_continuation_patterns,
        detect_breakout_patterns,
        detect_triangle_patterns,
        detect_ma_patterns,
        detect_divergence_patterns,
        detect_candlestick_patterns,
        detect_wyckoff_patterns,
    ]

    patterns: list[Pattern] = []
    for detector in detectors:
        try:
            patterns.extend(detector(df))
        except Exception as e:
            logger.debug("Pattern detector %s failed: %s", detector.__name__, e)

    return patterns
