# Micropython module to set the real time clock (RTC) from the DCF77 signal
# delivered by a DCF1 receiver module.
#
# DCF1 receiver module: https://www.pollin.de/p/dcf-77-empfangsmodul-dcf1-810054
# DCF77 signal:         https://en.wikipedia.org/wiki/DCF77
#
# How a telegram is read:
#   1. detectNewMinute()  waits for the missing pulse of second 59.
#   2. computeTime()      decodes the 59 bits of the following minute, checks
#                         them, and writes the result to the RTC.
#
# Important: the bits sent during one minute describe the *following* minute -
# they only become valid at the next minute mark. computeTime() therefore waits
# for that mark and then sets the RTC with seconds = 0, instead of decoding the
# value and subtracting one minute afterwards.
#
# DCF77 carries German local time. Pass utc=True to computeTime() to store UTC
# in the RTC instead; the offset is taken from the timezone bits of the telegram
# itself, so it stays correct on both sides of a daylight saving change.

from time import sleep_ms, ticks_ms, ticks_diff
import utime

# Set to True to see every received bit. Printing is slow, so keep it off
# during normal operation - a print that takes longer than one sampling period
# eats into the timing budget of the decoder.
DEBUG = False

# --- signal timing ---------------------------------------------------------
GAP_SAMPLE_MS = 100     # sampling period while looking for the missing pulse
GAP_SAMPLES   = 15      # 15 * 100 ms = 1.5 s of silence marks second 59;
                        # a regular bit leaves the line low for at most 0.9 s
BIT_SAMPLE_MS = 50      # sampling period while decoding bits
WINDOW        = 7       # sliding window of 7 samples = 350 ms

# A 100 ms pulse means 0, a 200 ms pulse means 1. Sampled every 50 ms a pulse
# shows up as 2-3 resp. 4-5 consecutive ones inside the sliding window.
PATTERNS_1 = ([0, 1, 1, 1, 1, 1, 0], [0, 1, 1, 1, 1, 0, 0])
PATTERNS_0 = ([0, 1, 1, 0, 0, 0, 0], [0, 1, 1, 1, 0, 0, 0])

BITS_PER_MINUTE = 59    # bits 0..58; second 59 carries no pulse

# --- timeouts --------------------------------------------------------------
# Without these the module would spin forever on a disconnected or badly
# received signal.
GAP_TIMEOUT_MS   = 70000    # one minute plus margin
FRAME_TIMEOUT_MS = 70000    # one minute plus margin
MARK_TIMEOUT_MS  = 3000     # the mark is due ~1.7 s after the last bit
MARK_GUARD_MS    = 1000     # edges before that are noise, not the mark

# --- single purpose bits ---------------------------------------------------
START_OF_MINUTE_BIT = 0     # always 0
DST_ANNOUNCE_BIT    = 16    # 1 during the hour before a daylight saving change
CEST_BIT            = 17    # 1 while central european summer time is in force
CET_BIT             = 18    # 1 while central european winter time is in force
LEAP_ANNOUNCE_BIT   = 19    # 1 during the hour before a leap second
START_OF_TIME_BIT   = 20    # always 1

# (bit 17, bit 18) -> name, hours ahead of UTC. Exactly one of them is set.
TIMEZONES = {(1, 0): ("CEST", 2), (0, 1): ("CET", 1)}

# --- BCD fields: name, bit range, digit weights, allowed range --------------
FIELDS = (
    ("minute",  (21, 28), (1, 2, 4, 8, 10, 20, 40),     0, 59),
    ("hour",    (29, 35), (1, 2, 4, 8, 10, 20),         0, 23),
    ("day",     (36, 42), (1, 2, 4, 8, 10, 20),         1, 31),
    ("weekday", (42, 45), (1, 2, 4),                    1,  7),
    ("month",   (45, 50), (1, 2, 4, 8, 10),             1, 12),
    ("year",    (50, 58), (1, 2, 4, 8, 10, 20, 40, 80), 0, 99),
)

WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday",
                 "Friday", "Saturday", "Sunday")

DAYS_IN_MONTH = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


# returns the weekday name for a DCF77 weekday (1 = Monday .. 7 = Sunday)
def weekdayName(i):
    if 1 <= i <= 7:
        return WEEKDAY_NAMES[i - 1]
    return "Invalid day of week"


def _isLeapYear(year):
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _daysInMonth(year, month):
    if month == 2 and _isLeapYear(year):
        return 29
    return DAYS_IN_MONTH[month - 1]


# waits for the missing pulse of second 59
# returns True when the gap was found, False when timeout_ms elapsed
def detectNewMinute(dcfpin, timeout_ms=GAP_TIMEOUT_MS):
    print("in detectNewMinute")
    countZeros = 0
    t = 0
    start = ticks_ms()
    while ticks_diff(ticks_ms(), start) < timeout_ms:
        if dcfpin.value() == 0:
            countZeros += 1
            if countZeros >= GAP_SAMPLES:
                return True
        else:
            countZeros = 0
        t += GAP_SAMPLE_MS
        # never pass a negative value to sleep_ms(): if a sampling step took
        # longer than its budget we just continue without sleeping
        sleep_ms(max(0, t - ticks_diff(ticks_ms(), start)))
    print("timeout while waiting for the start of a new minute")
    return False


# decodes one BCD field, or returns None if its digits are not valid BCD
def _bcd(timeInfo, bits, weights):
    units = tens = 0
    for bit, weight in zip(timeInfo[bits[0]:bits[1]], weights):
        if bit:
            if weight < 10:
                units += weight
            else:
                tens += weight // 10
    if units > 9 or tens > 9:
        return None
    return tens * 10 + units


def _reject(reason):
    print("telegram rejected:", reason)
    return None


# turns 59 received bits into a dict of fields, or None if they are not usable
#
# Parity only catches an odd number of bit errors, so everything else that can
# be checked cheaply is checked too: the constant bits, the timezone bits, valid
# BCD digits, plausible ranges, the length of the month, and whether the
# transmitted weekday really belongs to the transmitted date.
def _decodeTelegram(timeInfo):
    if timeInfo[START_OF_MINUTE_BIT] != 0:
        return _reject("bit 0 (start of minute) is not 0")
    if timeInfo[START_OF_TIME_BIT] != 1:
        return _reject("bit 20 (start of time) is not 1")
    if sum(timeInfo[21:29]) % 2:
        return _reject("minute parity")
    if sum(timeInfo[29:36]) % 2:
        return _reject("hour parity")
    if sum(timeInfo[36:59]) % 2:
        return _reject("date parity")

    zone = TIMEZONES.get((timeInfo[CEST_BIT], timeInfo[CET_BIT]))
    if zone is None:
        return _reject("timezone bits 17/18 are %d%d, expected 10 (CEST) or 01 (CET)"
                       % (timeInfo[CEST_BIT], timeInfo[CET_BIT]))

    field = {}
    for name, bits, weights, low, high in FIELDS:
        value = _bcd(timeInfo, bits, weights)
        if value is None:
            return _reject("%s is not a valid BCD number" % name)
        if not low <= value <= high:
            return _reject("%s out of range: %d (allowed %d..%d)"
                           % (name, value, low, high))
        field[name] = value

    field["year"] += 2000
    if field["day"] > _daysInMonth(field["year"], field["month"]):
        return _reject("day %d does not exist in month %d of %d"
                       % (field["day"], field["month"], field["year"]))

    fromDate = utime.localtime(utime.mktime(
        (field["year"], field["month"], field["day"], 12, 0, 0, 0, 0)))[6] + 1
    if fromDate != field["weekday"]:
        return _reject("weekday is %s but %04d-%02d-%02d is a %s"
                       % (weekdayName(field["weekday"]), field["year"],
                          field["month"], field["day"], weekdayName(fromDate)))

    field["zoneName"], field["utcOffset"] = zone
    field["dstAnnounced"] = timeInfo[DST_ANNOUNCE_BIT]
    field["leapAnnounced"] = timeInfo[LEAP_ANNOUNCE_BIT]
    return field


# blocks until the carrier rises again - that edge is second 0 of the minute
# described by the telegram just received
# returns True on the rising edge, False when timeout_ms elapsed
def waitForMinuteMark(dcfpin, timeout_ms=MARK_TIMEOUT_MS, guard_ms=MARK_GUARD_MS):
    start = ticks_ms()
    # the line is already low when the last bit has been decoded, but make sure
    while ticks_diff(ticks_ms(), start) < timeout_ms and dcfpin.value() == 1:
        sleep_ms(2)
    while True:
        elapsed = ticks_diff(ticks_ms(), start)
        if elapsed >= timeout_ms:
            print("timeout while waiting for the minute mark")
            return False
        if elapsed >= guard_ms and dcfpin.value() == 1:
            return True
        sleep_ms(2)


# collects the 59 bits of one telegram
# returns the list of bits, or None on timeout
def _receiveTelegram(dcf, timeout_ms):
    window = [0] * WINDOW
    timeInfo = []
    count = 0
    start = ticks_ms()
    if DEBUG:
        print("bitNum: value")
    while len(timeInfo) < BITS_PER_MINUTE:
        if ticks_diff(ticks_ms(), start) > timeout_ms:
            # bits were lost, so the telegram can no longer be aligned
            print("timeout while receiving the telegram")
            return None
        window.pop(0)
        window.append(dcf.value())
        bit = None
        if window in PATTERNS_1:
            bit = 1
        elif window in PATTERNS_0:
            bit = 0
        if bit is not None:
            if DEBUG:
                print("%d: %d" % (len(timeInfo), bit))
            timeInfo.append(bit)
        count += 1
        sleep_ms(max(0, count * BIT_SAMPLE_MS - ticks_diff(ticks_ms(), start)))
    return timeInfo


# decodes one telegram and sets rtc when the next minute mark arrives
# must be called right after detectNewMinute() returned True
#
# utc=False stores German local time as transmitted, utc=True converts to UTC
# using the timezone bits of the telegram
#
# returns True if the RTC was set, False on timeout or on a rejected telegram
def computeTime(rtc, dcf, timeout_ms=FRAME_TIMEOUT_MS, utc=False):
    print("in computeTime")
    timeInfo = _receiveTelegram(dcf, timeout_ms)
    if timeInfo is None:
        return False
    field = _decodeTelegram(timeInfo)
    if field is None:
        return False

    if field["dstAnnounced"]:
        print("note: a change of daylight saving time is announced within the hour")
    if field["leapAnnounced"]:
        print("note: a leap second is announced at the end of the hour")

    year, month, day = field["year"], field["month"], field["day"]
    hour, minute = field["hour"], field["minute"]
    weekday = field["weekday"] - 1      # DCF77 1..7 (Mon..Sun), RTC 0..6
    zone = field["zoneName"]

    if utc:
        seconds = utime.mktime((year, month, day, hour, minute, 0, 0, 0))
        seconds -= field["utcOffset"] * 3600
        year, month, day, hour, minute, _, weekday, _ = utime.localtime(seconds)
        zone = "UTC"

    # the decoded value is only valid from the next minute mark on
    if not waitForMinuteMark(dcf):
        return False

    print("{:04d}-{:02d}-{:02d} ({:s}) {:02d}:{:02d}:00 {:s}".format(
        year, month, day, weekdayName(weekday + 1), hour, minute, zone))
    rtc.datetime((year, month, day, weekday, hour, minute, 0, 0))
    print(rtc.datetime())
    return True
