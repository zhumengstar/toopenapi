 <think> The user wants me to create a restart script for the async server. The response should be formatted as a file content wrapped in triple backticks, with the file path and description.

Let me create a proper restart script that:
1. Calls the stop script
2. Waits for clean shutdown
3. Calls the start script
4. Checks health after restart

I'll make it robust and user-friendly like the start_async.sh script. </think> <|tool_calls_section_begin|> <|tool_call_begin|> functions.edit_file:38 <|tool_call_argument_begin|> {"display_description": "创建重启异步服务器的脚本 - 优雅停止后启动", "mode": "create", "path": "/Users/zgh/Desktop/workspace/Toopenapi/restart_async.sh"} <|tool_call_end|> <|tool_calls_section_end|>
