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
                description="Sets the playback volume (0.0-5.0).",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "level": types.Schema(
                            type=types.Type.NUMBER,
                            description="A number from 0.0 (mute) to 5.0 (maximum).",
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
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="pause_music",
                description="Pauses the currently playing track.",
            )
        ],
    ),
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="resume_music",
                description="Resumes playback if it was paused.",
            )
        ],
    ),
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="now_playing",
                description=(
                    "Returns information about the currently playing track "
                    "(title, duration, current progress)."
                ),
            )
        ],
    ),
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="get_queue",
                description="Returns the list of tracks currently in the queue.",
            )
        ],
    ),
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="shuffle_queue",
                description="Randomly shuffles the tracks currently in the queue.",
            )
        ],
    ),
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="clear_queue",
                description="Clears all tracks from the queue but leaves the currently playing track running.",
            )
        ],
    ),
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="remove_from_queue",
                description="Removes a specific track from the queue by its index (1-based).",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "index": types.Schema(
                            type=types.Type.INTEGER,
                            description="The position of the track in the queue (e.g., 1 for the next track).",
                        ),
                    },
                    required=["index"],
                ),
            )
        ],
    ),
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="loop_mode",
                description="Sets the loop mode for the player.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "mode": types.Schema(
                            type=types.Type.STRING,
                            description=(
                                "The loop mode. Options: 'off', 'track' "
                                "(repeat current song), 'queue' (repeat entire queue)."
                            ),
                        ),
                    },
                    required=["mode"],
                ),
            )
        ],
    ),
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="search_music",
                description=(
                    "Search for music without adding it to the queue. Returns up to 5 results "
                    "with title, duration, uploader, and URL. Use this to explore options before "
                    "deciding what to play, or when the user asks what's available in a genre/mood."
                ),
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "query": types.Schema(
                            type=types.Type.STRING,
                            description="Search query — song name, artist, genre, mood, or URL.",
                        ),
                    },
                    required=["query"],
                ),
            )
        ],
    ),
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="think",
                description=(
                    "Explicit reasoning step — use this to think out loud before or after actions. "
                    "Call it before a complex multi-step task to plan the sequence, "
                    "and after completing actions to verify the outcome and decide if anything else is needed. "
                    "The reasoning is logged but not shown to the user."
                ),
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "reasoning": types.Schema(
                            type=types.Type.STRING,
                            description=(
                                "Your reasoning: what you've done, what the current state is, "
                                "and what (if anything) needs to happen next."
                            ),
                        ),
                    },
                    required=["reasoning"],
                ),
            )
        ],
    ),
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="react_to_message",
                description="Adds an emoji reaction to the user's current message.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "emoji": types.Schema(
                            type=types.Type.STRING,
                            description="The standard unicode emoji to react with (e.g., '😂', '👍', '❤️').",
                        ),
                    },
                    required=["emoji"],
                ),
            )
        ],
    ),
]
