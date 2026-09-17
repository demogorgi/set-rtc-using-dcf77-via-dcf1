"""Test dcf2rtc against a simulated DCF77 signal. Runs on CPython, no hardware.

    python tests/test_dcf2rtc.py

A virtual clock drives both the module under test and a fake pin, so a whole
minute of radio traffic is decoded in milliseconds and cases that are awkward to
wait for in reality - midnight, new year, 29 February - are just another entry
in the table below.

Exits with status 1 if anything fails, so it can be used in CI.
"""
import sys, os, types, datetime, io, contextlib


# --- micropython modules the module under test imports ---------------------
class Clock:
    def __init__(self, t=0):
        self.t = t


clock = Clock()

fake_time = types.ModuleType("time")
fake_time.ticks_ms = lambda: clock.t
fake_time.ticks_diff = lambda a, b: a - b


def _sleep_ms(ms):
    # the module must never ask for a negative delay
    assert ms >= 0, "sleep_ms called with negative value %r" % ms
    clock.t += ms


fake_time.sleep_ms = _sleep_ms

# micropython counts from 2000-01-01; only differences matter here
EPOCH = datetime.datetime(2000, 1, 1)
fake_utime = types.ModuleType("utime")


def _mktime(t):
    y, mo, d, h, mi, s = t[:6]
    return int((datetime.datetime(y, mo, d, h, mi, s) - EPOCH).total_seconds())


def _localtime(secs):
    dt = EPOCH + datetime.timedelta(seconds=secs)
    yday = (dt - datetime.datetime(dt.year, 1, 1)).days + 1
    return (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
            dt.weekday(), yday)


fake_utime.mktime = _mktime
fake_utime.localtime = _localtime

sys.modules["time"] = fake_time
sys.modules["utime"] = fake_utime
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import dcf2rtc  # noqa: E402  (must come after the fake modules are installed)


# --- a DCF77 transmitter ---------------------------------------------------
def encode(dt, cest=True):
    """The 59 bits describing dt, the time this telegram becomes valid."""
    b = [0] * 59
    b[17], b[18] = (1, 0) if cest else (0, 1)
    b[20] = 1

    def bcd(start, weights, value):
        units, tens = value % 10, value // 10
        for i, w in enumerate(weights):
            b[start + i] = 1 if (units & w if w < 10 else tens & (w // 10)) else 0

    bcd(21, (1, 2, 4, 8, 10, 20, 40), dt.minute)
    b[28] = sum(b[21:28]) % 2
    bcd(29, (1, 2, 4, 8, 10, 20), dt.hour)
    b[35] = sum(b[29:35]) % 2
    bcd(36, (1, 2, 4, 8, 10, 20), dt.day)
    bcd(42, (1, 2, 4), dt.isoweekday())
    bcd(45, (1, 2, 4, 8, 10), dt.month)
    bcd(50, (1, 2, 4, 8, 10, 20, 40, 80), dt.year % 100)
    b[58] = sum(b[36:58]) % 2
    return b


class FakePin:
    """Rebuilds the modulated carrier from the virtual clock."""

    def __init__(self, t0_wall, cest=True, phase_ms=0):
        self.t0_wall, self.cest, self.phase = t0_wall, cest, phase_ms

    def value(self):
        t = clock.t - self.phase
        if t < 0:
            return 0
        minute_idx, rest = divmod(t, 60000)
        second, into = divmod(rest, 1000)
        if second >= 59:
            return 0                            # the missing 59th pulse
        # a telegram describes the minute that follows it
        valid_at = self.t0_wall + datetime.timedelta(minutes=minute_idx + 1)
        bit = encode(valid_at, self.cest)[second]
        return 1 if into < (200 if bit else 100) else 0


class FakeRTC:
    def __init__(self):
        self.set_to = None

    def datetime(self, tup=None):
        if tup is not None:
            self.set_to = tup
        return self.set_to


def decode_signal(t0_wall, cest=True, phase_ms=0, utc=False):
    clock.t = 45000                             # start inside second 45
    pin = FakePin(t0_wall, cest, phase_ms)
    rtc = FakeRTC()
    with contextlib.redirect_stdout(io.StringIO()):
        ok = dcf2rtc.detectNewMinute(pin) and dcf2rtc.computeTime(rtc, pin, utc=utc)
    return ok, rtc.set_to


def expected(wall, utc_offset=0):
    w = wall - datetime.timedelta(hours=utc_offset)
    return (w.year, w.month, w.day, w.isoweekday() - 1, w.hour, w.minute, 0, 0)


failures = []


def report(name, ok, detail=""):
    if not ok:
        failures.append(name + (": " + detail if detail else ""))
    print("  %-30s %s  %s" % (name, "ok  " if ok else "FAIL", detail))


# --- decoding a whole telegram off the air ---------------------------------
print("decoding the simulated signal")

CASES = (
    # name,                   telegram valid at,                   cest,  utc,  offset
    ("plain summer time",     datetime.datetime(2026, 9, 17, 12, 34),  True,  False, 0),
    ("minute rollover",       datetime.datetime(2026, 9, 17, 12, 58),  True,  False, 0),
    ("day rollover",          datetime.datetime(2026, 9, 17, 23, 58),  True,  False, 0),
    ("month rollover",        datetime.datetime(2026, 9, 30, 23, 58),  True,  False, 0),
    ("year rollover",         datetime.datetime(2026, 12, 31, 23, 58), False, False, 0),
    ("29 February",           datetime.datetime(2028, 2, 28, 23, 58),  False, False, 0),
    ("utc in summer (-2h)",   datetime.datetime(2026, 9, 17, 12, 34),  True,  True,  2),
    ("utc in winter (-1h)",   datetime.datetime(2026, 1, 15, 12, 34),  False, True,  1),
    ("utc across midnight",   datetime.datetime(2026, 9, 18, 0, 58),   True,  True,  2),
    ("utc across new year",   datetime.datetime(2026, 1, 1, 0, 58),    False, True,  1),
)

for name, t0, cest, utc, offset in CASES:
    results = []
    for phase in (0, 17, 33):                   # the sampling grid is not aligned
        results.append(decode_signal(t0, cest, phase, utc))
    want = expected(t0 + datetime.timedelta(minutes=2), offset)
    ok = all(r[0] and r[1] == want for r in results)
    report(name, ok, str(results[0][1]) if ok else "got %s want %s" % (results[0][1], want))

# --- telegrams that have to be thrown away ---------------------------------
print()
print("rejecting corrupted telegrams")

BASE = datetime.datetime(2026, 9, 17, 12, 35)


def check(name, bits, should_pass=False):
    with contextlib.redirect_stdout(io.StringIO()) as buf:
        accepted = dcf2rtc._decodeTelegram(bits) is not None
    reason = buf.getvalue().strip().replace("telegram rejected: ", "")
    report(name, accepted == should_pass, "accepted" if accepted else reason)


def broken(**kwargs):
    """A valid telegram with single bits overridden, parity repaired after."""
    b = encode(kwargs.pop("at", BASE), kwargs.pop("cest", True))
    for index, value in kwargs.pop("bits", {}).items():
        b[index] = value
    if kwargs.pop("repair_minute_parity", False):
        b[28] = sum(b[21:28]) % 2
    if kwargs.pop("repair_date_parity", False):
        b[58] = sum(b[36:58]) % 2
    assert not kwargs, kwargs
    return b


check("untouched (control)", encode(BASE), should_pass=True)
check("bit 0 not zero", broken(bits={0: 1}))
check("bit 20 not one", broken(bits={20: 0}))
check("minute parity broken", broken(bits={22: 1 - encode(BASE)[22]}))
check("hour parity broken", broken(bits={30: 1 - encode(BASE)[30]}))
check("date parity broken", broken(bits={38: 1 - encode(BASE)[38]}))
check("both timezone bits clear", broken(bits={17: 0, 18: 0}))
check("both timezone bits set", broken(bits={17: 1, 18: 1}))
check("minute is not bcd",                      # units nibble 1111
      broken(bits=dict(zip(range(21, 28), (1,) * 7)), repair_minute_parity=True))
check("month 13",
      broken(bits=dict(zip(range(45, 50), (1, 1, 0, 0, 1))), repair_date_parity=True))
check("day 32",
      broken(bits=dict(zip(range(36, 42), (0, 1, 0, 0, 1, 1))), repair_date_parity=True))
check("31 September",
      broken(at=datetime.datetime(2026, 9, 30, 12, 35),
             bits=dict(zip(range(36, 42), (1, 0, 0, 0, 1, 1))), repair_date_parity=True))
check("29 February in a common year",
      broken(at=datetime.datetime(2026, 2, 28, 12, 35),
             bits=dict(zip(range(36, 42), (1, 0, 0, 1, 0, 1))), repair_date_parity=True))
check("weekday contradicts the date",           # claims Monday for a Thursday
      broken(bits=dict(zip(range(42, 45), (1, 0, 0))), repair_date_parity=True))

# --- the bits that are not a number ----------------------------------------
print()
print("reading the announcement and timezone bits")


def field_of(bits):
    with contextlib.redirect_stdout(io.StringIO()):
        return dcf2rtc._decodeTelegram(bits)


report("dst change announced",
       field_of(broken(bits={16: 1}))["dstAnnounced"] == 1)
report("leap second announced",
       field_of(broken(bits={19: 1}))["leapAnnounced"] == 1)
f = field_of(encode(BASE, cest=False))
report("winter telegram says CET",
       (f["zoneName"], f["utcOffset"]) == ("CET", 1), f["zoneName"])
f = field_of(encode(BASE, cest=True))
report("summer telegram says CEST",
       (f["zoneName"], f["utcOffset"]) == ("CEST", 2), f["zoneName"])

print()
if failures:
    print("%d FAILED:" % len(failures))
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("all tests passed")
