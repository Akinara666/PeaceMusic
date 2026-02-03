from google.genai import types

tools = [
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="play_music",
                description="Starts playing a track or adds it to the queue by name or URL.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "song_name": types.Schema(
                            type=types.Type.STRING,
                            description="The name of the song to search for, or a direct link to the track.",
                        ),
                    },
                    required=["song_name"],
                ),
            )
        ],
    ),
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="stop_music",
                description="Stops playback and clears the queue. Use without parameters.",
            )
        ],
    ),
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="skip_music",
                description="Skips the current track and plays the next one in the queue, if available.",
            )
        ],
    ),
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="seek",
                description="Seeks to a specific timestamp in the currently playing track.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "time": types.Schema(
                            type=types.Type.STRING,
                            description="Time in 'HH:MM:SS' or 'MM:SS' format.",
                        ),
                    },
                    required=["time"],
                ),
            )
        ],
    ),
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="skip_music_by_name",
                description="Removes the specified song from the queue by name.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "song_name": types.Schema(
                            type=types.Type.STRING,
                            description="The name or part of the name to remove from the queue.",
                        ),
                    },
                    required=["song_name"],
                ),
            )
        ],
    ),
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="set_volume",
                description="Sets the playback volume (0.0-2.0).",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "level": types.Schema(
                            type=types.Type.NUMBER,
                            description="A number from 0.0 (mute) to 2.0 (maximum).",
                        ),
                    },
                    required=["level"],
                ),
            )
        ],
    ),
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="summon",
                description="Connects the bot to your voice channel or moves it there.",
            )
        ],
    ),
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="disconnect",
                description="Disconnects the bot from the voice channel and clears the queue.",
            )
        ],
    ),
]
