"""Build wall-clock time from the monotonic timer and the last RTC sync."""

import utime

DST_JUMP_THRESHOLD_MS = 30 * 60 * 1000


def _rtc_epoch(rtc_datetime):
    year, month, day, weekday, hour, minute, second = rtc_datetime[:7]
    return utime.mktime((year, month, day, hour, minute, second, weekday, 0))


class CorrectedClock:
    def set(self, rtc_datetime):
        rtc_epoch = _rtc_epoch(rtc_datetime)
        self._epoch_ms = rtc_epoch * 1000
        self._last_rtc_epoch = rtc_epoch
        self._last_tick = utime.ticks_ms()

    def now(self, rtc_datetime):
        tick = utime.ticks_ms()
        elapsed_ms = utime.ticks_diff(tick, self._last_tick)
        rtc_epoch = _rtc_epoch(rtc_datetime)
        rtc_elapsed_ms = (rtc_epoch - self._last_rtc_epoch) * 1000
        rtc_jump_ms = rtc_elapsed_ms - elapsed_ms

        if abs(rtc_jump_ms) >= DST_JUMP_THRESHOLD_MS:
            self._epoch_ms += rtc_jump_ms

        self._epoch_ms += elapsed_ms
        self._last_tick = tick
        self._last_rtc_epoch = rtc_epoch
        return utime.localtime(self._epoch_ms // 1000)
