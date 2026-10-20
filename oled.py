# Minimal MicroPython driver for the Wemos D1 mini OLED shield (0.66", 64x48,
# SSD1306). The controller has a 128x64 RAM of which the panel shows the middle
# 64 columns, so the column window starts at 32. No external dependency.
#
#   from machine import Pin, SoftI2C
#   i2c = SoftI2C(scl=Pin(5), sda=Pin(4), freq=400000)   # D1 = SCL, D2 = SDA
#   oled = SSD1306(i2c)
#   oled.text("Hello", 0, 0)                              # a framebuf.FrameBuffer
#   oled.show()

import framebuf

DEFAULT_CONTRAST = 128 # range is 0 to 255

_INIT = (
    (0xAE,),            # display off
    (0xD5, 0x80),       # clock divide / oscillator
    (0xA8, 0x2F),       # multiplex ratio: 48 rows
    (0xD3, 0x00),       # display offset
    (0x40,),            # start line 0
    (0x8D, 0x14),       # charge pump on
    (0x20, 0x00),       # horizontal addressing mode
    (0xA1,),            # segment remap
    (0xC8,),            # COM scan direction
    (0xDA, 0x12),       # COM pins
    (0xD9, 0xF1),       # pre-charge
    (0xDB, 0x40),       # VCOMH deselect
    (0xA4,),            # follow RAM content
    (0xA6,),            # not inverted
    (0xAF,),            # display on
)


class SSD1306(framebuf.FrameBuffer):
    def __init__(self, i2c, addr=0x3C, width=64, height=48):
        self.i2c = i2c
        self.addr = addr
        self.width = width
        self.height = height
        self.pages = height // 8
        self.column = (128 - width) // 2
        self.buffer = bytearray(self.pages * width)
        super().__init__(self.buffer, width, height, framebuf.MONO_VLSB)
        for cmd in _INIT:
            self._cmd(*cmd)
        self.contrast(contrast=DEFAULT_CONTRAST)
        self.fill(0)
        self.show()

    def _cmd(self, *cmd):
        self.i2c.writeto(self.addr, b"\x00" + bytes(cmd))

    def contrast(self, contrast):
        self._cmd(0x81, contrast)

    def poweroff(self):
        self._cmd(0xAE)

    def poweron(self):
        self._cmd(0xAF)

    def show(self):
        self._cmd(0x21, self.column, self.column + self.width - 1,
                  0x22, 0, self.pages - 1)
        self.i2c.writevto(self.addr, (b"\x40", self.buffer))
