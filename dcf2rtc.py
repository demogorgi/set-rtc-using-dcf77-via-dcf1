# Micropython module to set the real time clock (RTC) from the DCF77 signal
# delivered by a DCF1 receiver module.
#
# DCF1 receiver module: https://www.pollin.de/p/dcf-77-empfangsmodul-dcf1-810054
# DCF77 signal:         https://en.wikipedia.org/wiki/DCF77
#
# How a telegram is read:
#   1. detectNewMinute()  waits for the missing pulse of second 59.
#   2. computeTime()      decodes the 59 bits of the following minute and
#                         writes them to the RTC.
#
# Important: the bits sent during one minute describe the *following* minute -
# they only become valid at the next minute mark. computeTime() therefore waits
# for that mark and then sets the RTC with seconds = 0, instead of decoding the
# value and subtracting one minute afterwards.

from time import sleep_ms, ticks_ms, ticks_diff

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

# --- bit positions and BCD weights -----------------------------------------
MINUTE_BITS,  MINUTE_WEIGHTS  = (21, 28), (1, 2, 4, 8, 10, 20, 40)
HOUR_BITS,    HOUR_WEIGHTS    = (29, 35), (1, 2, 4, 8, 10, 20)
DAY_BITS,     DAY_WEIGHTS     = (36, 42), (1, 2, 4, 8, 10, 20)
WEEKDAY_BITS, WEEKDAY_WEIGHTS = (42, 45), (1, 2, 4)
MONTH_BITS,   MONTH_WEIGHTS   = (45, 50), (1, 2, 4, 8, 10)
YEAR_BITS,    YEAR_WEIGHTS    = (50, 58), (1, 2, 4, 8, 10, 20, 40, 80)

WEEKDAY_NAMES = ('Monday', 'Tuesday', 'Wednesday', 'Thursday',
                 'Friday', 'Saturday', 'Sunday')


# returns the weekday name for a DCF77 weekday (1 = Monday .. 7 = Sunday)
def weekday(i):
    if 1 <= i <= 7:
        return WEEKDAY_NAMES[i - 1]
    return "Invalid day of week"


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


# returns the integer encoded by timeInfo[bits[0]:bits[1]] in BCD
def _bcd(timeInfo, bits, weights):
    return sum(w for b, w in zip(timeInfo[bits[0]:bits[1]], weights) if b)


# checks the constant bits and the three even parity groups
# returns True if the telegram may be decoded
def _framingOk(timeInfo):
    if timeInfo[0] != 0 or timeInfo[20] != 1:
        return False
    return (sum(timeInfo[21:29]) % 2 == 0 and     # minute + parity
            sum(timeInfo[29:36]) % 2 == 0 and     # hour + parity
            sum(timeInfo[36:59]) % 2 == 0)        # date + parity


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


# decodes one telegram and sets rtc when the next minute mark arrives
# must be called right after detectNewMinute() returned True
# returns True if the RTC was set, False on timeout or on a corrupted telegram
def computeTime(rtc, dcf, timeout_ms=FRAME_TIMEOUT_MS):
    print("in computeTime")
    a = [0] * WINDOW
    timeInfo = []
    cnt = 0
    start = ticks_ms()
    if DEBUG:
        print("bitNum: value")
    while len(timeInfo) < BITS_PER_MINUTE:
        if ticks_diff(ticks_ms(), start) > timeout_ms:
            # bits were lost, so the telegram can no longer be aligned
            print("timeout while receiving the telegram")
            return False
        a.pop(0)
        a.append(dcf.value())
        bit = None
        if a in PATTERNS_1:
            bit = 1
        elif a in PATTERNS_0:
            bit = 0
        if bit is not None:
            if DEBUG:
                print("%d: %d" % (len(timeInfo), bit))
            timeInfo.append(bit)
        cnt += 1
        sleep_ms(max(0, cnt * BIT_SAMPLE_MS - ticks_diff(ticks_ms(), start)))

    if not _framingOk(timeInfo):
        print("severe error: parity bits or constant bits have unexpected values")
        return False

    minute    = _bcd(timeInfo, MINUTE_BITS,  MINUTE_WEIGHTS)
    stunde    = _bcd(timeInfo, HOUR_BITS,    HOUR_WEIGHTS)
    tag       = _bcd(timeInfo, DAY_BITS,     DAY_WEIGHTS)
    wochentag = _bcd(timeInfo, WEEKDAY_BITS, WEEKDAY_WEIGHTS)
    monat     = _bcd(timeInfo, MONTH_BITS,   MONTH_WEIGHTS)
    jahr      = 2000 + _bcd(timeInfo, YEAR_BITS, YEAR_WEIGHTS)

    # the decoded value is only valid from the next minute mark on
    if not waitForMinuteMark(dcf):
        return False

    print("{:04d}/{:02d}/{:02d} ({:s}) {:02d}:{:02d}:00".format(
        jahr, monat, tag, weekday(wochentag), stunde, minute))
    # DCF77 counts 1 = Monday .. 7 = Sunday, RTC.datetime() 0 = Monday .. 6 = Sunday
    rtc.datetime((jahr, monat, tag, wochentag - 1, stunde, minute, 0, 0))
    print(rtc.datetime())
    return True
