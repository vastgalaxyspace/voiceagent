from app.services.session_channel import SessionChannel


class Socket:
    def __init__(self):
        self.audio = []

    async def send_bytes(self, data):
        self.audio.append(data)


async def test_old_socket_cannot_detach_or_feed_new_attachment():
    channel = SessionChannel(1)
    old, current = Socket(), Socket()
    channel.attach(old)
    channel.forward(old, {'type': 'websocket.receive', 'bytes': b'old'})
    channel.detach(old)
    channel.attach(current)
    channel.forward(old, {'type': 'websocket.receive', 'bytes': b'stale'})
    channel.detach(old)
    assert channel.socket is current
    assert await channel.receive() == {'type': 'client.attached'}
    assert channel.incoming.empty()
    await channel.send_bytes(b'new')
    assert current.audio == [b'new'] and old.audio == []


async def test_input_pressure_is_bounded_and_stops_session():
    channel, socket = SessionChannel(1), Socket()
    channel.attach(socket)
    for _ in range(10):
        channel.forward(socket, {'type': 'websocket.receive', 'bytes': b'x'})
    assert channel.stop_reason == 'input_backpressure'
    assert channel.incoming.qsize() <= 8
