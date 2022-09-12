import cctime
import fs
import json
from http_fetcher import HttpFetcher
import prefs
from unpacker import Unpacker
import utils


# All durations are measured in milliseconds.
INITIAL_DELAY = 1000  # wait this long after booting up
INTERVAL_AFTER_FAILURE = 15000  # try again after 15 seconds
INTERVAL_AFTER_SUCCESS = 60 * 60 * 1000  # recheck for updates once an hour


class SoftwareUpdater:
    def __init__(self, app, network, clock_mode):
        self.app = app
        self.network = network
        self.clock_mode = clock_mode

        self.api_url = prefs.get('api_url')
        self.api_fetcher = None
        self.api_file = None
        self.api_fetched = None

        self.update_url = prefs.get('update_url')
        self.index_fetcher = None
        self.index_file = None
        self.index_name = None
        self.index_updated = None
        self.index_fetched = None
        self.index_packs = None
        self.unpacker = None

        self.retry_after(INITIAL_DELAY)

    def retry_after(self, delay):
        self.network.close_step()
        self.api_fetcher = None
        self.index_fetcher = None
        self.unpacker = None
        self.next_check = cctime.monotonic_millis() + delay
        self.step = self.wait_step
        utils.log(f'Next software update attempt in {delay} ms.')

    def wait_step(self):
        if cctime.monotonic_millis() > self.next_check:
            print('fetch')
            addr = self.network.get_hardware_address()
            now = cctime.millis_to_isoformat(cctime.get_millis())
            v = utils.version_running()
            vp = ','.join(utils.versions_present())
            afetch = cctime.millis_to_isoformat(self.api_fetched) or ''
            ifetch = cctime.millis_to_isoformat(self.index_fetched) or ''
            fc = self.app.frame_counter
            self.api_fetcher = HttpFetcher(self.network,
                f'{self.api_url}?p=ac&mac={addr}&v={v}&vp={vp}&t={now}&af={afetch}&if={ifetch}&up={fc.uptime()}&fps={fc.fps:.1f}&mem={fc.min_free}&disk={fs.free_kb()}')
            self.step = self.api_fetch_step

    def api_fetch_step(self):
        try:
            data = self.api_fetcher.read()
            if data:
                if not self.api_file:
                    self.api_file = fs.open('/cache/clock.json.new', 'wb')
                self.api_file.write(data)
            return
        except Exception as e:
            self.api_fetcher = None
            if self.api_file:
                self.api_file.close()
                self.api_file = None
            if isinstance(e, StopIteration):
                fs.move('/cache/clock.json.new', '/cache/clock.json')
            else:
                utils.report_error(e, 'API fetch aborted')
                self.network.close_step()
                # Continue with software update anyway
                self.index_fetcher = HttpFetcher(self.network, self.update_url)
                self.step = self.index_fetch_step
                return

        # StopIteration means fetch was successfully completed
        utils.log(f'API file successfully fetched!')
        self.api_fetched = cctime.get_millis()
        self.clock_mode.reload_definition()

        self.index_fetcher = HttpFetcher(self.network, self.update_url)
        self.step = self.index_fetch_step

    def index_fetch_step(self):
        try:
            data = self.index_fetcher.read()
            if data:
                if not self.index_file:
                    self.index_file = fs.open('/cache/packs.json', 'wb')
                self.index_file.write(data)
            return
        except Exception as e:
            self.index_fetcher = None
            if self.index_file:
                self.index_file.close()
                self.index_file = None
            if not isinstance(e, StopIteration):
                utils.report_error(e, 'Index fetch aborted')
                self.retry_after(INTERVAL_AFTER_FAILURE)
                return
        # StopIteration means fetch was successfully completed
        utils.log(f'Index file successfully fetched!')
        self.index_fetched = cctime.get_millis()
        try:
            with fs.open('/cache/packs.json') as index_file:
                pack_index = json.load(index_file)
            self.index_name = pack_index['name']
            self.index_updated = pack_index['updated']
            self.index_packs = pack_index['packs']
        except Exception as e:
            utils.report_error(e, 'Unreadable index file')
            self.retry_after(INTERVAL_AFTER_FAILURE)
            return

        version = get_latest_enabled_version(self.index_packs)
        if version:
            latest, url, dir_name = version
            print(f'Latest enabled version is {dir_name} at {url}.')
            if fs.isfile(dir_name + '/@VALID'):
                print(f'{dir_name} already exists and is valid.')
                write_enabled_flags(self.index_packs)
                self.retry_after(INTERVAL_AFTER_SUCCESS)
            else:
                self.index_fetcher = None
                self.unpacker = Unpacker(HttpFetcher(self.network, url))
                self.step = self.pack_fetch_step
        else:
            print(f'No enabled versions found.')
            self.retry_after(INTERVAL_AFTER_SUCCESS)

    def pack_fetch_step(self):
        try:
            done = self.unpacker.step()
        except Exception as e:
            utils.report_error(e, 'Pack fetch aborted')
            self.retry_after(INTERVAL_AFTER_FAILURE)
        else:
            if done:
                write_enabled_flags(self.index_packs)
                self.retry_after(INTERVAL_AFTER_SUCCESS)


def get_latest_enabled_version(index_packs):
    latest = None
    for pack_name, props in index_packs.items():
        enabled = props.get('enabled')
        pack_hash = props.get('hash', '')
        url = props.get('url', '')
        try:
            assert pack_hash
            assert url
            assert pack_name.startswith('v')
            num = int(pack_name[1:])
        except:
            print(f'Ignoring invalid pack entry: {pack_name}')
            continue
        if enabled:
            version = (num, url, pack_name + '.' + pack_hash)
            if not latest or version > latest:
                latest = version
    return latest


def write_enabled_flags(index_packs):
    for pack_name, props in index_packs.items():
        enabled = props.get('enabled')
        pack_hash = props.get('hash', '')
        dir_name = pack_name + '.' + pack_hash
        if fs.isdir(dir_name):
            fs.destroy(dir_name + '/@ENABLED')
            if enabled:
                print('Enabled:', dir_name)
                fs.write(dir_name + '/@ENABLED', b'')
            else:
                print('Disabled:', dir_name)
