import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from live_listen.server import _mix_call_frame, _clear_mix_state, ulaw_to_pcm16, _ulaw2lin

IMG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "images")


def _frame(byte_val, count=160):
    return ulaw_to_pcm16(bytes([byte_val] * count))


def test_mix_single_track_streams_at_normal_rate():
    _clear_mix_state("CA-MIX-A")
    # Single track: every new 20ms slot flushes the previous frame as-is.
    first = _mix_call_frame("CA-MIX-A", "inbound", _frame(0xFF), "0")
    assert first is None
    second = _mix_call_frame("CA-MIX-A", "inbound", _frame(0xFF), "20")
    assert second == _frame(0xFF)
    _clear_mix_state("CA-MIX-A")


def test_mix_two_tracks_produce_one_frame_per_slot():
    _clear_mix_state("CA-MIX-B")
    # 0xFF ulaw decodes to 0, 0x00 ulaw decodes to -32124.
    assert _ulaw2lin(0xFF) == 0
    assert _ulaw2lin(0x00) == -32124

    inbound = _frame(0xFF)   # all zeros
    outbound = _frame(0x00)  # all -32124

    got = _mix_call_frame("CA-MIX-B", "inbound", inbound, "0")
    assert got is None  # still accumulating
    got = _mix_call_frame("CA-MIX-B", "outbound", outbound, "0")
    assert got is not None  # slot complete -> one mixed frame
    # Sum of the two decoded tracks, clamped, single 160-sample frame.
    expected = ulaw_to_pcm16(bytes([0x00] * 160))
    assert got == expected
    # Duplicate frame for same slot+track is ignored.
    assert _mix_call_frame("CA-MIX-B", "inbound", inbound, "0") is None
    _clear_mix_state("CA-MIX-B")


def test_mix_does_not_double_broadcast_two_tracks():
    _clear_mix_state("CA-MIX-C")
    # Two full 20ms windows of two tracks -> exactly two frames (normal speed),
    # i.e. the browser gets 2 frames for 2 windows, not 4 (the 2x-speed bug).
    frames = []
    for ts, byte_in, byte_out in [
        ("0", 0xFF, 0x00),
        ("20", 0xFF, 0x00),
    ]:
        f = _mix_call_frame("CA-MIX-C", "inbound", _frame(byte_in), ts)
        assert f is None
        f = _mix_call_frame("CA-MIX-C", "outbound", _frame(byte_out), ts)
        frames.append(f)
    assert len(frames) == 2
    _clear_mix_state("CA-MIX-C")