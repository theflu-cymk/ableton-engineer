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

from Enableton.server import Bridge, resolve_song


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
