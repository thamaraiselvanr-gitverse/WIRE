"""Per-user usage quotas (abuse control).

Rate limiting caps bursts per minute; the quota caps total reconstructions per
user per day. Configurable via ``WIRE_DAILY_RECONSTRUCTION_QUOTA``.
"""

import os

_DEFAULT_DAILY_QUOTA = 50


def daily_reconstruction_quota() -> int:
    try:
        return max(1, int(os.environ.get("WIRE_DAILY_RECONSTRUCTION_QUOTA", "")))
    except (TypeError, ValueError):
        return _DEFAULT_DAILY_QUOTA
