import socket
import threading
import unittest

import support  # noqa: F401  (path setup)
from enableton.protocol.framing import (
    FrameReader,
    FramingError,
    encode_frame,
)

import Enableton.framing as script_framing


class FramingTests(unittest.TestCase):
    def test_round_trip(self):
        reader = FrameReader()
        frames = reader.feed(encode_frame({"id": 1, "ok": True}))
        self.assertEqual(frames, [{"id": 1, "ok": True}])

    def test_partial_frames(self):
        payload = encode_frame({"id": 7, "cmd": "song.summary"})
        reader = FrameReader()
        self.assertEqual(reader.feed(payload[:2]), [])
        self.assertEqual(reader.feed(payload[2:5]), [])
        self.assertEqual(reader.feed(payload[5:]), [{"id": 7, "cmd": "song.summary"}])
        self.assertEqual(reader.pending(), 0)

    def test_byte_at_a_time(self):
        payload = encode_frame({"id": 3})
        reader = FrameReader()
        frames = []
        for i in range(len(payload)):
            frames.extend(reader.feed(payload[i:i + 1]))
        self.assertEqual(frames, [{"id": 3}])

    def test_coalesced_frames(self):
        reader = FrameReader()
        frames = reader.feed(encode_frame({"a": 1}) + encode_frame({"b": 2}))
        self.assertEqual(frames, [{"a": 1}, {"b": 2}])

    def test_rejects_oversize(self):
        reader = FrameReader(max_frame=16)
        with self.assertRaises(FramingError):
            reader.feed(b"\x00\x00\x01\x00" + b"{}")

    def test_rejects_bad_json(self):
        body = b"not json"
        with self.assertRaises(FramingError):
            FrameReader().feed(b"\x00\x00\x00\x08" + body)

    def test_rejects_non_object(self):
        with self.assertRaises(FramingError):
            FrameReader().feed(encode_frame([1, 2, 3]))

    def test_script_and_server_framing_interoperate(self):
        # The two implementations are duplicated at the boundary; prove they agree.
        server_bytes = encode_frame({"id": 42, "cmd": "track.list"})
        self.assertEqual(script_framing.FrameReader().feed(server_bytes),
                         [{"id": 42, "cmd": "track.list"}])

        script_bytes = script_framing.encode_frame({"id": 42, "ok": True, "result": {}})
        self.assertEqual(FrameReader().feed(script_bytes),
                         [{"id": 42, "ok": True, "result": {}}])

    def test_script_framing_handles_partial(self):
        payload = script_framing.encode_frame({"id": 9})
        reader = script_framing.FrameReader()
        self.assertEqual(reader.feed(payload[:-1]), [])
        self.assertEqual(reader.feed(payload[-1:]), [{"id": 9}])


if __name__ == "__main__":
    unittest.main()
