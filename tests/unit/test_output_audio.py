import wave

import pytest

from app.storage.output_audio import OutputAudioRecorder


@pytest.mark.asyncio
async def test_output_audio_recorder_writes_playable_wav(tmp_path):
    recorder = OutputAudioRecorder(tmp_path, 'conversation-id')
    recorder.append(b'\x01\x00\x02\x00')

    path = await recorder.complete_turn()

    assert path == tmp_path / 'conversation-id_turn_001.wav'
    with wave.open(str(path), 'rb') as audio:
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        assert audio.getframerate() == 24000
        assert audio.readframes(2) == b'\x01\x00\x02\x00'


@pytest.mark.asyncio
async def test_output_audio_recorder_saves_unfinished_audio_as_partial(tmp_path):
    recorder = OutputAudioRecorder(tmp_path, 'conversation-id')
    recorder.append(b'\x00\x00')

    path = await recorder.close()

    assert path.name == 'conversation-id_turn_001_partial.wav'
