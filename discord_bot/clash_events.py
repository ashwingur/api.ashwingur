from datetime import datetime, timedelta, time, timezone
from calendar import monthrange

UTC = timezone.utc

def last_monday_of_month(year, month):
    """Get the last Monday of the given month at 5am UTC."""
    last_day = monthrange(year, month)[1]
    for day in range(last_day, 0, -1):
        dt = datetime(year, month, day, 5, 0, tzinfo=UTC)
        if dt.weekday() == 0:  # Monday
            return dt
    return None

def get_event_status(now, start, end):
    if start <= now < end:
        return True, end, end - now
    elif now < start:
        return False, start, start - now
    else:
        return False, None, None

def get_clash_events(now=None):
    if now is None:
        now = datetime.now(UTC)
    year, month = now.year, now.month

    # ===== Trophy Season =====
    # Last 5AM UTC, last monday of each month
    this_month_last_monday = last_monday_of_month(year, month)
    if now >= this_month_last_monday:
        next_month = month + 1 if month < 12 else 1
        next_year = year if month < 12 else year + 1
        next_month_last_monday = last_monday_of_month(next_year, next_month)
        season_start = this_month_last_monday
        season_end = next_month_last_monday
    else:
        prev_month = month - 1 if month > 1 else 12
        prev_year = year if month > 1 else year - 1
        prev_month_last_monday = last_monday_of_month(prev_year, prev_month)
        season_start = prev_month_last_monday
        season_end = this_month_last_monday
    season_ongoing, season_time, season_remaining = get_event_status(now, season_start, season_end)

    # ===== Clan Games =====
    # 8AM 22nd - 8AM 28th every month
    cg_start = datetime(year, month, 22, 8, tzinfo=UTC)
    cg_end = datetime(year, month, 28, 8, tzinfo=UTC)
    if now >= cg_end:
        next_month = month + 1 if month < 12 else 1
        next_year = year if month < 12 else year + 1
        cg_start = datetime(next_year, next_month, 22, 8, tzinfo=UTC)
        cg_end = datetime(next_year, next_month, 28, 8, tzinfo=UTC)
    clan_ongoing, clan_time, clan_remaining = get_event_status(now, cg_start, cg_end)

    # ===== Raid Weekend =====
    # Starts Friday 7am UTC, ends Monday 7am UTC
    weekday = now.weekday()

    # Find the most recent Friday
    days_since_friday = (weekday - 4) % 7
    last_friday = datetime.combine((now - timedelta(days=days_since_friday)).date(), time(7, 0), tzinfo=UTC)
    raid_start = last_friday
    raid_end = raid_start + timedelta(days=3)  # Friday 7am to Monday 7am

    # If we've passed this weekend's end, calculate the next
    if now >= raid_end:
        raid_start += timedelta(days=7)
        raid_end += timedelta(days=7)

    raid_ongoing, raid_time, raid_remaining = get_event_status(now, raid_start, raid_end)

    # ===== Gold Pass =====
    gp_start = datetime(year, month, 1, 8, tzinfo=UTC)
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1
    gp_end = datetime(next_year, next_month, 1, 8, tzinfo=UTC)

    if now < gp_start:
        prev_month = month - 1 if month > 1 else 12
        prev_year = year if month > 1 else year - 1
        gp_start = datetime(prev_year, prev_month, 1, 7, tzinfo=UTC)
        gp_end = datetime(year, month, 1, 7, tzinfo=UTC)

    gold_ongoing, gold_time, gold_remaining = get_event_status(now, gp_start, gp_end)

    return [
        {
            "event": "Trophy Season",
            "ongoing": season_ongoing,
            "datetime": season_time,
            "time_remaining": season_remaining,
        },
        {
            "event": "Clan Games",
            "ongoing": clan_ongoing,
            "datetime": clan_time,
            "time_remaining": clan_remaining,
        },
        {
            "event": "Raid Weekend",
            "ongoing": raid_ongoing,
            "datetime": raid_time,
            "time_remaining": raid_remaining,
        },
        {
            "event": "Season Pass",
            "ongoing": gold_ongoing,
            "datetime": gold_time,
            "time_remaining": gold_remaining,
        },
    ]
