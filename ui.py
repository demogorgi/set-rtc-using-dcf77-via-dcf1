# Shows what dcf2rtc is doing on the 64x48 OLED: searching for the minute gap,
# the progress and the bits of the telegram being received, why a telegram was
# thrown away, and - once the RTC is set - a clock.
#
# Plug display.handle into dcf2rtc.observer. The decoder samples the signal
# every 50 ms, so the screen is only redrawn when a bit has just been completed
# (the line is silent for the next ~600 ms) and never inside the sampling
# window of a pulse.

import framebuf
from time import localtime, sleep_ms

WEEKDAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")

# first match wins; the display is only 8 characters wide
REASONS = (
    ("parity", "PARITAET"), ("timezone", "ZEITZONE"), ("BCD", "BCD"),
    ("range", "BEREICH"), ("exist", "DATUM"), ("weekday", "WOCHENTG"),
    ("bit 0", "STARTBIT"), ("bit 20", "ZEITBIT"),
)


class Display:
    def __init__(self, oled, utc=False, source="DCF77"):
        self.oled = oled
        self.utc = utc
        self.source = source
        self.attempt = 0
        self.failed = False
        self._lastSecond = -1
        self._glyph = framebuf.FrameBuffer(bytearray(8), 8, 8, framebuf.MONO_VLSB)

    # --- drawing helpers ----------------------------------------------------
    def _header(self, text):
        self.oled.fill(0)
        self.oled.fill_rect(0, 0, 64, 9, 1)
        self.oled.text(text, 0, 1, 0)

    def _big(self, text, x, y, pitch, scale=2):
        for ch in text:
            self._glyph.fill(0)
            self._glyph.text(ch, 0, 0, 1)
            for gx in range(8):
                for gy in range(8):
                    if self._glyph.pixel(gx, gy):
                        self.oled.fill_rect(x + gx * scale, y + gy * scale,
                                            scale, scale, 1)
            x += pitch

    def _bar(self, y, value, total):
        self.oled.rect(0, y, 64, 6, 1)
        self.oled.fill_rect(2, y + 2, value * 60 // total, 2, 1)

    def _tape(self, bits):
        # one cell per bit: a filled square is a 1, a single dot is a 0
        for i, bit in enumerate(bits):
            x = 2 + (i % 20) * 3
            y = 29 + (i // 20) * 4
            if bit:
                self.oled.fill_rect(x, y, 2, 2, 1)
            else:
                self.oled.pixel(x, y, 1)

    # --- screens ------------------------------------------------------------
    def _tower(self, cx, top, base):
        o = self.oled
        o.line(cx, top, cx - 7, base, 1)
        o.line(cx, top, cx + 7, base, 1)
        o.line(cx - 4, top + (base - top) * 5 // 9, cx + 4, top + (base - top) * 5 // 9, 1)
        o.line(cx - 2, top + (base - top) * 8 // 9, cx + 2, top + (base - top) * 8 // 9, 1)
        o.fill_rect(cx - 1, top - 2, 3, 3, 1)

    def alternating_splash(self):
        o = self.oled
        message = "NTP UND DCF IM WECHSEL"
        for x in range(64, -len(message) * 8 - 1, -3):
            o.fill(0)
            o.fill_rect(0, 0, 64, 9, 1)
            o.text("ZEIT AUS", 0, 1, 0)
            o.ellipse(15, 20, 8, 8, 1)
            o.ellipse(15, 20, 3, 8, 1)
            o.hline(7, 20, 17, 1)
            o.line(25, 20, 38, 20, 1)
            o.line(25, 20, 29, 17, 1)
            o.line(25, 20, 29, 23, 1)
            o.line(38, 20, 34, 17, 1)
            o.line(38, 20, 34, 23, 1)
            self._tower(49, 13, 29)
            o.text("NTP", 3, 31, 1)
            o.text("DCF", 42, 31, 1)
            o.fill_rect(0, 40, 64, 8, 0)
            o.text(message, x, 40, 1)
            o.show()
            sleep_ms(35)

    # animated start screen, about 7 s: a mast sends out radio waves, the name
    # appears letter by letter, then the author's address scrolls past
    def splash(self):
        o = self.oled
        cx, cy = 32, 17
        for frame in range(40):
            o.fill(0)
            for k in range(3):
                r = (frame * 2 + k * 9) % 24 + 5
                o.ellipse(cx, cy, r, r, 1)
            # waves only radiate upwards from the tip of the mast
            o.fill_rect(0, cy + 2, 64, 30, 0)
            self._tower(cx, cy, 30)
            o.hline(0, 30, 64, 1)
            o.text("DCF77", 12, 37, 1)
            o.show()
            sleep_ms(40)
        word = "DCF77"
        for i in range(len(word) + 1):
            o.fill(0)
            self._big(word[:i], 2, 6, 12)
            o.text("Funkuhr" if i == len(word) else "", 4, 28, 1)
            o.rect(0, 40, 64, 6, 1)
            o.fill_rect(2, 42, i * 60 // len(word), 2, 1)
            o.show()
            sleep_ms(250)
        credit = "github.com/demogorgi"
        for x in range(64, -8 * len(credit) - 1, -3):
            o.fill_rect(0, 38, 64, 10, 0)
            o.text(credit, x, 39, 1)
            o.show()
            sleep_ms(25)
        sleep_ms(500)

    def ntp_splash(self):
        o = self.oled
        for frame in range(24):
            o.fill(0)
            o.ellipse(32, 17, 11, 11, 1)
            o.ellipse(32, 17, 5, 11, 1)
            o.hline(21, 17, 23, 1)
            o.line(32, 17, 32 + (frame % 6) - 2, 11, 1)
            o.line(32, 17, 37, 17, 1)
            o.text("NTP", 20, 34, 1)
            o.text("INTERNET", 0, 42, 1)
            o.show()
            sleep_ms(100)

    def search(self, seconds):
        self._header("DCF77")
        self.oled.text("SUCHE", 0, 11, 1)
        # a block sweeping back and forth shows that the loop is alive
        pos = seconds * 6 % 104
        pos = pos if pos <= 52 else 104 - pos
        self.oled.rect(0, 22, 64, 6, 1)
        self.oled.fill_rect(2 + pos, 24, 8, 2, 1)
        self.oled.text("V%d %ds" % (self.attempt + 1, seconds), 0, 40, 1)
        self.oled.show()

    def receive(self, bits):
        self._header("DCF77 RX")
        self.oled.text("EMPFANG", 0, 11, 1)
        self._bar(21, len(bits), 59)
        self._tape(bits)
        self.oled.text("%d/59 V%d" % (len(bits), self.attempt), 0, 40, 1)
        self.oled.show()

    def status(self, title, line1, line2=""):
        self._header(title)
        self.oled.text(line1, 0, 14, 1)
        self.oled.text(line2, 0, 26, 1)
        self.oled.text("V%d" % self.attempt, 0, 40, 1)
        self.oled.show()

    def clock(self, now=None):
        if now is None:
            now = localtime()
        if now[5] == self._lastSecond:
            return
        self._lastSecond = now[5]
        year, month, day, hour, minute, second, weekday = now[:7]
        self._header("UTC  OK" if self.utc else self.source + " OK")
        # four 16 px digits at a pitch of 14 px leave room for the colon
        self._big("%02d" % hour, 0, 12, 14)
        self._big("%02d" % minute, 36, 12, 14)
        if second % 2 == 0:
            self.oled.fill_rect(31, 16, 2, 2, 1)
            self.oled.fill_rect(31, 22, 2, 2, 1)
        self._bar(31, second, 59)
        self.oled.text("%s %02d.%02d" % (WEEKDAYS[weekday], day, month), 0, 40, 1)
        self.oled.show()

    # --- dcf2rtc.observer ---------------------------------------------------
    def handle(self, event, *args):
        if self.failed:
            return
        try:
            self._handle(event, *args)
        except OSError as e:
            # a missing display must never stop the clock from being set
            self.failed = True
            print("OLED disabled:", e)

    def _handle(self, event, *args):
        if event == "search":
            self.search(args[0] // 1000)
        elif event == "receive":
            self.attempt += 1
            self.receive([])
        elif event == "bit":
            self.receive(args[2])
        elif event == "valid":
            self.status("DCF77", "PRUEFE", "OK")
        elif event == "rejected":
            short = "?"
            for key, text in REASONS:
                if key in args[0]:
                    short = text
                    break
            self.status("DCF77", "FEHLER", short)
        elif event == "timeout":
            self.status("DCF77", "TIMEOUT", args[0].upper()[:8])
        elif event == "set":
            self._lastSecond = -1
            self.clock()
