"""Test corrected wall time against a monotonic millisecond clock."""
import datetime
import os
import sys
import types

EPOCH = datetime.datetime(2000, 1, 1)
fake_utime = types.ModuleType("utime")
fake_utime.tick = 0


def mktime(value):
    year, month, day, hour, minute, second = value[:6]
    value = datetime.datetime(year, month, day, hour, minute, second)
    return int((value - EPOCH).total_seconds())


def localtime(seconds):
    value = EPOCH + datetime.timedelta(seconds=seconds)
    yday = (value - datetime.datetime(value.year, 1, 1)).days + 1
    return (value.year, value.month, value.day, value.hour, value.minute,
            value.second, value.weekday(), yday)


def ticks_diff(new, old):
    return new - old


fake_utime.mktime = mktime
fake_utime.localtime = localtime
fake_utime.ticks_ms = lambda: fake_utime.tick
fake_utime.ticks_diff = ticks_diff
sys.modules["utime"] = fake_utime
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from timebase import CorrectedClock


def check(label, actual, expected):
    assert actual[:6] == expected[:6], "%s: expected %r, got %r" % (
        label, expected, actual)
    print("  %-28s ok" % label)


print("corrected clock uses monotonic elapsed time")
fake_utime.tick = 0
rtc = (2026, 10, 20, 1, 12, 0, 0, 0)
clock = CorrectedClock()
clock.set(rtc)
fake_utime.tick += 60000
rtc = (2026, 10, 20, 1, 12, 1, 5, 0)
check("ignores fast RTC drift", clock.now(rtc),
      (2026, 10, 20, 12, 1, 0, 1, 294))

fake_utime.tick = 0
rtc = (2026, 3, 29, 6, 1, 59, 59, 0)
clock = CorrectedClock()
clock.set(rtc)
fake_utime.tick += 1000
rtc = (2026, 3, 29, 6, 3, 0, 0, 0)
check("preserves spring DST jump", clock.now(rtc),
      (2026, 3, 29, 3, 0, 0, 6, 88))

fake_utime.tick = 0
rtc = (2026, 10, 25, 6, 2, 59, 59, 0)
clock = CorrectedClock()
clock.set(rtc)
fake_utime.tick += 1000
rtc = (2026, 10, 25, 6, 2, 0, 0, 0)
check("preserves fall DST jump", clock.now(rtc),
      (2026, 10, 25, 2, 0, 0, 6, 298))

print("all tests passed")
