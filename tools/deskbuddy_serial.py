"""Minimal USB-serial helper (stdlib only; pyserial is not required)."""
import glob
import os
import select
import sys
import termios
import time


def find_port():
    ports = sorted(glob.glob("/dev/cu.usbmodem*"))
    if not ports:
        sys.exit("no /dev/cu.usbmodem* port found; is the ESP32-C3 plugged in?")
    return ports[0]


class Serial:
    def __init__(self, port, settle=1.5):
        self.fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        attrs = termios.tcgetattr(self.fd)
        attrs[0] = attrs[1] = attrs[3] = 0          # raw
        attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        attrs[4] = attrs[5] = termios.B115200
        attrs[6][termios.VMIN], attrs[6][termios.VTIME] = 0, 0
        termios.tcsetattr(self.fd, termios.TCSANOW, attrs)
        self.buf = b""
        time.sleep(settle)  # opening the port may toggle DTR; give the board time to settle

    def close(self):
        os.close(self.fd)

    def write_line(self, text):
        data = (text + "\n").encode()
        view = memoryview(data)
        while view:  # long lines (the CA) exceed the pipe size, so respect back-pressure
            _, w, _ = select.select([], [self.fd], [], 5)
            if not w:
                raise TimeoutError("serial write stalled")
            n = os.write(self.fd, view[:256])
            view = view[n:]
            time.sleep(0.005)

    def read_lines(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            r, _, _ = select.select([self.fd], [], [], 0.2)
            if r:
                chunk = os.read(self.fd, 4096)
                self.buf += chunk
            while b"\n" in self.buf:
                line, _, self.buf = self.buf.partition(b"\n")
                yield line.decode("utf-8", "replace").rstrip("\r")

    def command(self, text, timeout=5.0, show=True):
        """Send one command and return the first OK/ERR reply line."""
        self.write_line(text)
        for line in self.read_lines(timeout):
            if line.startswith(("OK", "ERR")):
                return line
            if show and not line.startswith(("FETCH", "RENDER", "BOOT")):
                pass
        return "ERR timeout waiting for reply"
