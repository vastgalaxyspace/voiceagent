from google.genai import types

from app.services.live_tools import ToolSession
from app.services.usage import Measurements
from tests.helpers.fakes import settings


def test_duplicate_argument_order_has_the_same_signature():
    tools = ToolSession(None, settings(), None, None, None,
                        Measurements('gemini-3.8-live', 'unknown'), 300)
    first = types.FunctionCall(id='same-call', name='search_knowledge', args={'query': 'Kotlin', 'limit': 3})
    reordered = types.FunctionCall(id='same-call', name='search_knowledge', args={'limit': 3, 'query': 'Kotlin'})
    assert tools.accept(first) and tools.accept(reordered)
    assert len(tools.seen) == 1 and tools.measurements.tool_call_count == 2
    tools.clear()
    assert not tools.seen and not tools.cache and not tools.cancelled
