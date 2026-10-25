"""Normalize completed native results, not assistant descriptions of tools.

Reviewed parent source SHA-256:
7669a53efcfd70d16635e91ba01e2a53130726720745bdabab2ac78bd0549c18
"""
def tool_results(events):
    results = {}
    for event in events:
        if event.get('type') == 'tool_execution_end':
            results[event['toolCallId']] = {
                'tool_call_id': event['toolCallId'], 'tool_name': event.get('toolName'),
                'result': event.get('result', {}), 'is_error': event.get('isError', False)}
    # Installed Pi also publishes completed toolResult messages without a
    # separate tool_execution_end. Prefer the final, hook-modified message.
    for event in events:
        message = event.get('message', {})
        if event.get('type') == 'message_end' and message.get('role') == 'toolResult':
            results[message['toolCallId']] = {
                'tool_call_id': message['toolCallId'], 'tool_name': message.get('toolName'),
                'result': message, 'is_error': message.get('isError', False)}
    return list(results.values())
