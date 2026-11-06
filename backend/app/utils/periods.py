from datetime import date, datetime, timedelta, timezone
import calendar


def month_bounds(d: date) -> tuple[date, date]:
    first = d.replace(day=1)
    last_day = calendar.monthrange(d.year, d.month)[1]
    last = d.replace(day=last_day)
    return first, last


def week_index(d: date) -> int:
    """1-based week within month: days 1-7 -> 1, 8-14 -> 2, ..., 29-31 -> 5."""
    return (d.day - 1) // 7 + 1


def week_bounds(d: date) -> tuple[date, date]:
    idx = week_index(d)
    first_day = d.replace(day=1)
    start = first_day + timedelta(days=(idx - 1) * 7)
    candidate_end = start + timedelta(days=6)
    _, last = month_bounds(d)
    return start, min(candidate_end, last)


def as_dt_start(d: date) -> datetime:
    return datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc)


def as_dt_end(d: date) -> datetime:
    return datetime.combine(d, datetime.max.time(), tzinfo=timezone.utc)