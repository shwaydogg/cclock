import ccapi
from ccinput import ButtonReader, DialReader, Press
import cctime
import ccui
from mode import Mode
from updater import SoftwareUpdater
import utils
from utils import Cycle, mem


class ClockMode(Mode):
    def __init__(self, app, fs, network, button_map, dial_map):
        mem('pre-ClockMode.__init__')
        super().__init__(app)
        self.fs = fs
        self.network = network

        self.updater = SoftwareUpdater(fs, network, app.prefs, self)
        mem('SoftwareUpdater')
        self.deadline = None
        self.lifeline = None
        self.message_module = ccapi.Newsfeed()
        mem('Newsfeed')
        self.message_module.type = 'newsfeed'
        self.message_module.items = [ccapi.NewsfeedItem()]
        mem('NewsfeedItems')

        self.reload_definition()
        mem('reload_definition')

        self.reader = ButtonReader({
            button_map['UP']: {
                Press.SHORT: 'NEXT_LANGUAGE',
                Press.LONG: 'TOGGLE_CAPS',
            },
            button_map['DOWN']: {
                Press.SHORT: 'NEXT_LIFELINE',
                Press.LONG: 'MENU_MODE',
            },
            button_map['ENTER']: {
                Press.SHORT: 'NEXT_LIFELINE',
                Press.SHORT: 'MENU_MODE',
            }
        })
        mem('ButtonReader')
        self.dial_reader = DialReader('SELECTOR', dial_map['SELECTOR'], 1)
        mem('DialReader')
        self.force_caps = False

    def reload_definition(self):
        try:
            with self.fs.open('/cache/clock.json') as api_file:
                defn = ccapi.load(api_file)
                self.deadline = defn.module_dict['carbon_deadline_1']
                modules = [self.message_module]
                modules += [m for m in defn.modules if m.flavor == 'lifeline']
                self.lifelines = Cycle(*modules)
                self.lifeline = self.lifelines.current()
                display = defn.config.display
                self.deadline_cv = self.frame.pack(*display.deadline.primary)
                self.lifeline_cv = self.frame.pack(*display.lifeline.primary)
        except Exception as e:
            utils.report_error(e, 'Could not load API file')

    def start(self):
        self.reader.reset()
        self.dial_reader.reset()
        self.frame.clear()
        auto_cycling = self.app.prefs.get('auto_cycling')
        self.next_advance = auto_cycling and cctime.get_millis() + auto_cycling

        self.updates_paused_until_millis = cctime.try_isoformat_to_millis(
            self.app.prefs, 'updates_paused_until')

        ccui.reset_newsfeed()
        item = self.message_module.items[0]
        item.headline = self.app.prefs.get('custom_message')
        item.source = ''

    def step(self):
        if self.next_advance and cctime.get_millis() > self.next_advance:
            auto_cycling = self.app.prefs.get('auto_cycling')
            if auto_cycling:
                self.next_advance += auto_cycling
            else:
                self.next_advance = None
            self.lifeline = self.lifelines.next()
            self.frame.clear()

        self.frame.clear()
        if not self.deadline:
            cv = self.frame.pack(255, 255, 255)
            self.frame.print(1, 0, 'Loading...', 'kairon-10', cv)
        if self.deadline:
            ccui.render_deadline_module(
                self.frame, 0, self.deadline,
                self.deadline_cv, self.app.lang, self.force_caps)
        if self.lifeline:
            ccui.render_lifeline_module(
                self.frame, 16, self.lifeline,
                self.lifeline_cv, self.app.lang, self.force_caps)
        self.reader.step(self.app.receive)
        self.dial_reader.step(self.app.receive)
        self.frame.send()

        if cctime.get_millis() > (self.updates_paused_until_millis or 0):
            self.updater.step()

    def receive(self, command, arg=None):
        if command == 'TOGGLE_CAPS':
            self.force_caps = not self.force_caps
            self.frame.clear()
        if command == 'NEXT_LIFELINE':
            self.lifeline = self.lifelines.next()
            self.frame.clear()
        if command == 'SELECTOR':
            delta, value = arg
            if delta > 0:
                self.lifeline = self.lifelines.next()
            else:
                self.lifeline = self.lifelines.previous()
            self.frame.clear()
