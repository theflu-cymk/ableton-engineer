"""The threading design, tested without Live.

The bridge is the part most likely to be wrong in a way that only shows up as a mysterious
timeout inside Live, so it is a plain class with no Live dependency and it is tested here.
"""

import threading
import time
import unittest

import support
from enableton.live.fake import build_song
from enableton.protocol.client import LiveClient
from enableton.protocol.codes import LiveError

from Enableton.server import Bridge, _safe_log, resolve_song


class BridgeTests(unittest.TestCase):
    def _bridge_with_pump(self):
        song = build_song()
        bridge = Bridge(lambda: song, port=0)
        bridge.start()
        self.addCleanup(bridge.stop)
        self.assertNotEqual(bridge.port, 9878, "port=0 must not steal Live's port")

        stop = threading.Event()

        def pump():
            while not stop.is_set():
                bridge.drain()
                time.sleep(0.005)

        worker = threading.Thread(target=pump, daemon=True)
        worker.start()

        def finish():
            stop.set()
            worker.join(timeout=2.0)

        self.addCleanup(finish)
        return bridge, song

    def test_work_runs_only_when_drained(self):
        bridge, song = self._bridge_with_pump()
        client = LiveClient(port=bridge.port, default_timeout_ms=2000)
        client.connect()
        self.addCleanup(client.close)

        self.assertEqual(client.call("snapshot.get", {})["counts"]["tracks"], 3)
        self.assertTrue(client.call("transport.play", {})["is_playing"])
        self.assertTrue(song.is_playing)

    def test_without_draining_the_request_is_busy_not_silent(self):
        song = build_song()
        bridge = Bridge(lambda: song, port=0)
        bridge.start()
        self.addCleanup(bridge.stop)

        client = LiveClient(port=bridge.port, default_timeout_ms=2000)
        client.connect()
        self.addCleanup(client.close)

        started = time.time()
        with self.assertRaises(LiveError) as ctx:
            client.call("snapshot.get", {}, timeout_ms=150)
        elapsed = time.time() - started

        self.assertEqual(ctx.exception.code, "LIVE_BUSY")
        self.assertLess(elapsed, 2.0, "the bridge must answer, not hang")

    def test_bridge_answers_before_the_client_gives_up(self):
        """The bridge's deadline must be shorter than the client's watchdog.

        With ``timeout_s + 0.5`` the bridge replied LIVE_BUSY *after* the client had already
        raised TIMEOUT and discarded the reply, which is why an undrained queue was
        indistinguishable from a dead script.
        """
        song = build_song()
        bridge = Bridge(lambda: song, port=0)
        bridge.start()
        self.addCleanup(bridge.stop)

        client = LiveClient(port=bridge.port, default_timeout_ms=400)
        client.connect()
        self.addCleanup(client.close)

        with self.assertRaises(LiveError) as ctx:
            client.call("snapshot.get", {}, timeout_ms=300)
        self.assertEqual(ctx.exception.code, "LIVE_BUSY")

    def test_hello_never_enters_the_queue(self):
        song = build_song()
        bridge = Bridge(lambda: song, port=0)
        bridge.start()
        self.addCleanup(bridge.stop)

        client = LiveClient(port=bridge.port)
        client.connect()
        self.addCleanup(client.close)

        # No pump running: hello must still answer, because it touches no LOM.
        info = client.handshake()
        self.assertEqual(info["protocol"], 1)


    def test_hello_reports_queue_depth_and_counters(self):
        song = build_song()
        bridge = Bridge(lambda: song, port=0)
        bridge.start()
        self.addCleanup(bridge.stop)

        client = LiveClient(port=bridge.port)
        client.connect()
        self.addCleanup(client.close)

        info = client.handshake()
        self.assertEqual(info["queued"], 0)
        self.assertEqual(info["stats"]["drains"], 0)
        # A frozen ``drains`` is ambiguous until these exist: Live never ticked the surface, or
        # the framework's own super().update_display() raised before our drain ran.
        self.assertEqual(info["stats"]["display"], 0)
        self.assertEqual(info["stats"]["super_errors"], 0)

    def test_drain_counters_distinguish_not_ticked_from_lost_reply(self):
        """A timeout must be attributable: was the work never run, or was the reply lost?"""
        bridge, _song = self._bridge_with_pump()
        client = LiveClient(port=bridge.port, default_timeout_ms=2000)
        client.connect()
        self.addCleanup(client.close)

        client.call("snapshot.get", {})
        info = client.handshake()
        self.assertEqual(info["stats"]["ran"], 1)
        self.assertGreaterEqual(info["stats"]["drains"], 1)


    def test_a_deferred_command_resumes_on_a_later_tick(self):
        """The playhead moves between ticks, so a cue command must not answer in one drain."""
        song = build_song()
        bridge = Bridge(lambda: song, port=0)
        bridge.start()
        self.addCleanup(bridge.stop)

        box, done = {}, threading.Event()
        bridge._queue.put((
            "sections.create_locators",
            {"sections": [{"name": "gate", "bar": 2}], "dry_run": False},
            box,
            done,
        ))
        bridge.drain()
        self.assertFalse(done.is_set(), "a deferred command answered inside one tick")
        self.assertEqual(song.locators, [])

        for _ in range(20):
            if done.is_set():
                break
            song.tick()
            bridge.drain()
        self.assertTrue(done.is_set(), "the deferred command never finished")
        self.assertIn("result", box)
        self.assertEqual(
            [(locator.name, locator.time) for locator in song.locators],
            [("gate", 4.0)],
        )


class SafeLogTests(unittest.TestCase):
    """Logging is diagnostics: it must never be able to abort construction.

    Live 12.2.5 has no ``log_message`` on the surface, and raising from ``__init__`` left the socket
    alive with no surface to tick ``update_display`` — ``connected yes``, ``display 0``, every command
    stalled.
    """

    def test_uses_log_message_when_present(self):
        calls = []

        class Target(object):
            def log_message(self, text):
                calls.append(text)

        _safe_log(Target(), "hi")
        self.assertEqual(calls, ["hi"])

    def test_falls_back_to_the_c_instance(self):
        calls = []

        class Instance(object):
            def log_message(self, text):
                calls.append(text)

        class Target(object):
            _c_instance = Instance()

        _safe_log(Target(), "hi")
        self.assertEqual(calls, ["hi"])

    def test_never_raises_when_nothing_can_log(self):
        _safe_log(object(), "hi")

    def test_survives_a_logger_that_raises(self):
        class Target(object):
            def log_message(self, text):
                raise RuntimeError("nope")

        _safe_log(Target(), "hi")


class CallableSong(object):
    """Live's LOM objects answer ``callable()`` truthily, then raise when invoked.

    This is the exact shape that made ``ControlSurface.song`` fail on Live 12 with
    "'Song' object is not callable": guarding on ``callable(song)`` picks the wrong branch.
    """

    def __call__(self, *args):
        raise TypeError("'Song' object is not callable")


class PropertySurface(object):
    """Live 12: ``song`` is a property returning a Song object."""

    def __init__(self):
        self._song = CallableSong()

    @property
    def song(self):
        return self._song


class MethodSurface(object):
    """Older frameworks: ``song`` is a method that must be called."""

    def __init__(self):
        self._song = CallableSong()

    def song(self):
        return self._song


class SongShapeTests(unittest.TestCase):
    def test_property_song_is_never_invoked(self):
        surface = PropertySurface()
        self.assertIs(resolve_song(surface), surface._song)

    def test_method_song_is_invoked(self):
        surface = MethodSurface()
        self.assertIs(resolve_song(surface), surface._song)


if __name__ == "__main__":
    unittest.main()
