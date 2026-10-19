"""Synchronize the RTC from NTP, optionally storing German local time."""

import utime


def _last_sunday(year, month):
    days_in_month = (31, 29 if year % 4 == 0 and
                     (year % 100 != 0 or year % 400 == 0) else 28,
                     31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    last_day = days_in_month[month - 1]
    weekday = utime.localtime(utime.mktime(
        (year, month, last_day, 0, 0, 0, 0, 0)))[6]
    return last_day - ((weekday + 1) % 7)


def germanLocalTime(utc_time):
    year, month, day, hour, minute, second = utc_time[:6]
    if 3 < month < 10:
        offset = 2
    elif month < 3 or month > 10:
        offset = 1
    elif month == 3:
        change_day = _last_sunday(year, month)
        offset = 2 if day > change_day or (
            day == change_day and hour >= 1) else 1
    else:
        change_day = _last_sunday(year, month)
        offset = 1 if day > change_day or (
            day == change_day and hour >= 1) else 2

    local = utime.localtime(utime.mktime(utc_time) + offset * 3600)
    return (local[0], local[1], local[2], local[6], local[3], local[4],
            local[5], 0)


def syncTime(rtc, utc=False):
    import ntptime

    ntptime.settime()
    if not utc:
        rtc.datetime(germanLocalTime(utime.localtime()))
