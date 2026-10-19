"""Test NTP time conversion at German daylight-saving boundaries."""
import datetime
import os
import sys
import types

EPOCH = datetime.datetime(2000, 1, 1)
fake_utime = types.ModuleType("utime")


def mktime(value):
    year, month, day, hour, minute, second = value[:6]
    dt = datetime.datetime(year, month, day, hour, minute, second)
    return int((dt - EPOCH).total_seconds())


def localtime(seconds):
    dt = EPOCH + datetime.timedelta(seconds=seconds)
    yday = (dt - datetime.datetime(dt.year, 1, 1)).days + 1
    return (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
            dt.weekday(), yday)


fake_utime.mktime = mktime
fake_utime.localtime = localtime
sys.modules["utime"] = fake_utime
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import ntp2rtc


def check(label, utc, expected):
    actual = ntp2rtc.germanLocalTime(utc)
    assert actual == expected, "%s: expected %r, got %r" % (
        label, expected, actual)
    print("  %-28s ok" % label)


print("converting NTP UTC to German local time")
check("winter CET", (2026, 1, 15, 12, 0, 0, 3, 15),
      (2026, 1, 15, 3, 13, 0, 0, 0))
check("DST starts before transition", (2026, 3, 29, 0, 59, 0, 6, 88),
      (2026, 3, 29, 6, 1, 59, 0, 0))
check("DST starts at 01:00 UTC", (2026, 3, 29, 1, 0, 0, 6, 88),
      (2026, 3, 29, 6, 3, 0, 0, 0))
check("DST ends before transition", (2026, 10, 25, 0, 59, 0, 6, 298),
      (2026, 10, 25, 6, 2, 59, 0, 0))
check("DST ends at 01:00 UTC", (2026, 10, 25, 1, 0, 0, 6, 298),
      (2026, 10, 25, 6, 2, 0, 0, 0))
check("new year rollover", (2026, 12, 31, 23, 30, 0, 3, 365),
      (2027, 1, 1, 4, 0, 30, 0, 0))
print("all tests passed")
