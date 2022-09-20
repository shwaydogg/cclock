import ccapi
import cctime
from ccinput import DialReader
from clock_mode import ClockMode
import display
import gc
from menu_mode import MenuMode
import micropython
import network
from pref_entry_mode import PrefEntryMode
import utils


class App:
    def __init__(self, bitmap, net, button_map, dial_map):
        utils.log('Starting App.__init__')
        self.bitmap = bitmap
        self.net = net
        self.frame_counter = FrameCounter()

        self.clock_mode = ClockMode(self, net, button_map, dial_map)
        utils.log('Created ClockMode')
        self.menu_mode = MenuMode(self, button_map, dial_map)
        utils.log('Created MenuMode')
        self.pref_entry_mode = PrefEntryMode(self, button_map, dial_map)
        utils.log('Created PrefEntryMode')
        self.mode = self.clock_mode

        self.langs = utils.Cycle('en', 'es', 'de', 'fr', 'is')
        self.lang = self.langs.get()
        self.brightness_reader = DialReader(
            'BRIGHTNESS', dial_map['BRIGHTNESS'], 3/32.0, 0.01, 0.99)
        utils.log('Finished App.__init__')

    def start(self):
        display.set_brightness(self.brightness_reader.value)
        self.mode.start()

    def step(self):
        self.frame_counter.tick()
        self.brightness_reader.step(self.receive)
        self.mode.step()

    def receive(self, command, arg=None):
        print('[' + command + ('' if arg is None else ': ' + str(arg)) + ']')
        if command == 'BRIGHTNESS':
            delta, value = arg
            display.set_brightness(value)
        if command == 'NEXT_LANGUAGE':
            self.lang = self.langs.get(1)
            self.bitmap.fill(0)
        if command == 'CLOCK_MODE':
            self.set_mode(self.clock_mode)
        if command == 'MENU_MODE':
            self.set_mode(self.menu_mode)
        if command == 'WIFI_SSID_MODE':
            self.pref_entry_mode.set_pref('Wi-Fi network name', 'wifi_ssid')
            self.set_mode(self.pref_entry_mode)
        if command == 'WIFI_PASSWORD_MODE':
            self.pref_entry_mode.set_pref('Wi-Fi password', 'wifi_password')
            self.set_mode(self.pref_entry_mode)
        if command == 'CUSTOM_MESSAGE_MODE':
            self.pref_entry_mode.set_pref(
                'Custom message', 'custom_message', True)
            self.set_mode(self.pref_entry_mode)
        if command == 'DUMP_MEMORY':
            gc.collect()
            micropython.mem_info(1)
        if command == 'DUMP_FRAME':
            print('[[FRAME]]')
            rgbs = ['%02x%02x%02x' % display.get_rgb(pi) for pi in range(16)]
            for i in range(192*32):
                print(rgbs[self.bitmap[i]], end='')
            print()
            gc.collect()

        self.mode.receive(command, arg)

    def set_mode(self, mode):
        self.bitmap.fill(0)
        self.mode = mode
        mode.start()


class FrameCounter:
    def __init__(self):
        self.start = cctime.monotonic_millis()
        self.fps = 0
        self.last_tick = self.start
        self.min_free = utils.free()

    def tick(self):
        now = cctime.monotonic_millis()
        elapsed = now - self.last_tick
        if elapsed > 0:
            last_fps = 1000.0/elapsed
            self.fps = 0.9 * self.fps + 0.1 * last_fps
        last_sec = self.last_tick//1000
        now_sec = now//1000
        if now_sec > last_sec:
            print('|\n', end='')
            if now_sec % 10 == 0:
                utils.log(f'Up {self.uptime()} s ({self.fps:.1f} fps) on {utils.version_running()}')
                self.min_free = min(self.min_free, utils.free())
        print('.', end='')
        self.last_tick = now

    def uptime(self):
        now = cctime.monotonic_millis()
        return (now - self.start)//1000


def run(bitmap, esp, socklib, button_map, dial_map):
    utils.log('Starting run')
    cctime.enable_rtc()
    net = network.Network(esp, socklib)
    app = App(bitmap, net, button_map, dial_map)
    app.start()
    utils.log('First frame')
    while True:
        app.step()
