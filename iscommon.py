from datetime import datetime
from tzlocal import get_localzone  # type: ignore


class ISAPIException (Exception):
    pass


def localize_timestamp(raw: datetime) -> datetime:
    tz = get_localzone()
    try:
        return tz.localize(raw, is_dst=None)  # type: ignore
    except Exception:
        return tz.localize(raw, is_dst=True)  # type: ignore
