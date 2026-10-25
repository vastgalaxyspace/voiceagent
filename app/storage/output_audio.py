"""Opt-in local WAV capture for debugging assistant audio output."""
import asyncio
from pathlib import Path
import wave


class OutputAudioRecorder:
    """Collect provider PCM chunks and save one WAV file per completed turn."""

    def __init__(self, directory: Path, conversation_id: str):
        self.directory = directory
        self.conversation_id = conversation_id
        self.buffer = bytearray()
        self.turn = 0

    def append(self, pcm: bytes) -> None:
        self.buffer.extend(pcm)

    async def complete_turn(self, *, partial: bool = False) -> Path | None:
        if not self.buffer:
            return None
        pcm = bytes(self.buffer)
        self.buffer.clear()
        self.turn += 1
        suffix = '_partial' if partial else ''
        path = self.directory / f'{self.conversation_id}_turn_{self.turn:03d}{suffix}.wav'

        def write() -> None:
            self.directory.mkdir(parents=True, exist_ok=True)
            with wave.open(str(path), 'wb') as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(24000)
                output.writeframes(pcm)

        await asyncio.to_thread(write)
        return path

    async def close(self) -> Path | None:
        return await self.complete_turn(partial=True)
