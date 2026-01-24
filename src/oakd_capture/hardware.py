"""Simple button and buzzer control using gpiozero."""

import time
import threading
from typing import Callable

# GPIO pins (BCM numbering)
BUTTON_PIN = 17
BUZZER_PIN = 18

# Timing
BEEP_DURATION = 0.15
BEEP_GAP = 0.15
BUTTON_COOLDOWN = 1.0


class Buzzer:
    """Simple buzzer with beep patterns."""

    def __init__(self, pin: int = BUZZER_PIN, active_high: bool = False):
        """Initialize buzzer. active_high=False for 3.3V active buzzers (LOW=on)."""
        from gpiozero import OutputDevice
        self._buzzer = OutputDevice(pin, active_high=active_high, initial_value=False)
        self._lock = threading.Lock()

    def beep(self, count: int = 1) -> None:
        """Blocking beep pattern."""
        with self._lock:
            for i in range(count):
                self._buzzer.on()
                time.sleep(BEEP_DURATION)
                self._buzzer.off()
                if i < count - 1:
                    time.sleep(BEEP_GAP)

    def beep_async(self, count: int = 1) -> threading.Thread:
        """Non-blocking beep pattern."""
        thread = threading.Thread(target=self.beep, args=(count,), daemon=True)
        thread.start()
        return thread

    def ready(self) -> None:
        """3 beeps - device ready."""
        self.beep(3)

    def start(self) -> None:
        """1 beep - recording started."""
        self.beep(1)

    def stop(self) -> None:
        """2 beeps - recording stopped."""
        self.beep(2)

    def error(self) -> None:
        """Long beep - error."""
        with self._lock:
            self._buzzer.on()
            time.sleep(0.5)
            self._buzzer.off()

    def cleanup(self) -> None:
        """Release GPIO resources."""
        self._buzzer.close()


class Button:
    """Simple button with debounce and cooldown."""

    def __init__(self, pin: int = BUTTON_PIN):
        """Initialize button with pull-up resistor."""
        from gpiozero import Button as GpioButton
        self._button = GpioButton(pin, pull_up=True, bounce_time=0.2)
        self._callback: Callable | None = None
        self._last_press = 0.0
        self._lock = threading.Lock()

    def set_callback(self, callback: Callable) -> None:
        """Set callback for button press with cooldown protection."""
        self._callback = callback
        self._button.when_pressed = self._on_press

    def _on_press(self) -> None:
        """Handle button press with cooldown."""
        with self._lock:
            now = time.monotonic()
            if now - self._last_press < BUTTON_COOLDOWN:
                return
            self._last_press = now

        if self._callback:
            self._callback()

    def cleanup(self) -> None:
        """Release GPIO resources."""
        self._button.close()


class Hardware:
    """Combined hardware manager."""

    def __init__(self):
        self.buzzer = Buzzer()
        self.button = Button()

    def cleanup(self) -> None:
        """Release all GPIO resources."""
        self.buzzer.cleanup()
        self.button.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.cleanup()
