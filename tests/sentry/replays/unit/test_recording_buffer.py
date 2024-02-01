import datetime
from unittest.mock import patch

import pytest
import time_machine

from sentry.replays.consumers.recording_buffered import (
    BufferCommitFailed,
    RecordingBuffer,
    commit_uploads,
)


def test_recording_buffer_commit_default():
    """Test RecordingBuffer commit readiness."""
    # Assert all.
    buffer = RecordingBuffer(0, 0, 0)
    assert buffer.has_exceeded_max_message_count
    assert buffer.has_exceeded_buffer_byte_size
    assert buffer.has_exceeded_last_buffer_commit_time
    assert buffer.is_ready

    # Assert none.
    buffer = RecordingBuffer(1, 1, 1)
    assert not buffer.has_exceeded_max_message_count
    assert not buffer.has_exceeded_buffer_byte_size
    assert not buffer.has_exceeded_last_buffer_commit_time
    assert not buffer.is_ready

    # Assert deadline.
    buffer = RecordingBuffer(1, 1, 0)
    assert not buffer.has_exceeded_max_message_count
    assert not buffer.has_exceeded_buffer_byte_size
    assert buffer.has_exceeded_last_buffer_commit_time
    assert buffer.is_ready

    # Assert size.
    buffer = RecordingBuffer(1, 0, 1)
    assert not buffer.has_exceeded_max_message_count
    assert buffer.has_exceeded_buffer_byte_size
    assert not buffer.has_exceeded_last_buffer_commit_time
    assert buffer.is_ready

    # Assert max messages.
    buffer = RecordingBuffer(0, 1, 1)
    assert buffer.has_exceeded_max_message_count
    assert not buffer.has_exceeded_buffer_byte_size
    assert not buffer.has_exceeded_last_buffer_commit_time
    assert buffer.is_ready


def test_recording_buffer_commit_deadline():
    buffer = RecordingBuffer(
        max_buffer_message_count=1_000_000,  # Never triggers commit.
        max_buffer_size_in_bytes=1_000_000,  # Never triggers commit.
        max_buffer_time_in_seconds=5,
    )

    now = datetime.datetime.now()

    # New buffer; never at expiration.
    traveller = time_machine.travel(now)
    traveller.start()
    assert not buffer.has_exceeded_last_buffer_commit_time
    assert not buffer.is_ready
    traveller.stop()

    # Almost at expiration.
    traveller = time_machine.travel(now + datetime.timedelta(seconds=4))
    traveller.start()
    assert not buffer.has_exceeded_last_buffer_commit_time
    assert not buffer.is_ready
    traveller.stop()

    # Exactly at expiration.
    traveller = time_machine.travel(now + datetime.timedelta(seconds=5))
    traveller.start()
    assert buffer.has_exceeded_last_buffer_commit_time
    assert buffer.is_ready  # type: ignore
    traveller.stop()

    # 55 seconds after expiration.
    traveller = time_machine.travel(now + datetime.timedelta(seconds=60))
    traveller.start()
    assert buffer.has_exceeded_last_buffer_commit_time
    assert buffer.is_ready
    traveller.stop()


def test_recording_buffer_commit_next_state():
    now = datetime.datetime(year=2024, month=1, day=1)

    # Create the initial state.
    traveller = time_machine.travel(now)
    traveller.start()
    buffer = RecordingBuffer(
        max_buffer_message_count=1_000_000,  # Never triggers commit.
        max_buffer_size_in_bytes=1_000_000,  # Never triggers commit.
        max_buffer_time_in_seconds=5,
    )
    traveller.stop()

    # Advance time by 10 seconds to trigger a commit.
    traveller = time_machine.travel(now + datetime.timedelta(seconds=10))
    traveller.start()

    # Cache the first deadline for later use.
    first_deadline = buffer._buffer_next_commit_time

    # Functionally a no-op but we do reset the buffer to a new empty state.
    buffer = buffer.new()

    # A new deadline was generated by the call to commit.
    second_deadline = buffer._buffer_next_commit_time

    assert first_deadline < second_deadline
    # Deadlines incremented at exactly the rate of time travelled.
    assert first_deadline + 10 == second_deadline
    # Deadline advanced by 15 seconds compared to previous buffer's start time.
    assert second_deadline == int((now + datetime.timedelta(seconds=15)).timestamp())

    traveller.stop()


@patch("sentry.replays.consumers.recording_buffered._do_upload")
def test_commit_uploads(_do_upload):
    """Assert successful batch does not error."""

    def mocked(u):
        return None

    _do_upload.side_effect = mocked

    commit_uploads([{}])  # type: ignore


@patch("sentry.replays.consumers.recording_buffered._do_upload")
def test_commit_uploads_failure(_do_upload):
    """Assert _do_upload failure rate limits the consumer process."""

    def mocked(u):
        raise ValueError("")

    _do_upload.side_effect = mocked

    with pytest.raises(BufferCommitFailed):
        commit_uploads([{}])  # type: ignore
