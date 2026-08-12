from __future__ import annotations

import asyncio
from types import SimpleNamespace

from peacemusic.adapters.discord.cogs.music import MusicCog
from peacemusic.adapters.discord.cogs.memory import MemoryCog
from peacemusic.adapters.discord.cogs.dj import DJCog
from peacemusic.adapters.discord.cogs.playlists import PlaylistCog
from peacemusic.adapters.discord.cogs.settings import SettingsCog
from peacemusic.core.errors import PermissionDeniedError
from peacemusic.modules.music.models import LoopMode, Track
from peacemusic.modules.music.player import GuildPlayer
from peacemusic.modules.settings.models import GuildSettings
from peacemusic.modules.agent.state import PeaceMusicState
from peacemusic.modules.playlists.models import Playlist, PlaylistTrack
from peacemusic.adapters.discord.cogs.chat import ChatCog
from peacemusic.adapters.discord.views.settings import (
    AIChannelSetupView,
    AISetupView,
    SetupAutoplayView,
    SetupDJRoleView,
    SetupMentionView,
    SetupView,
    SetupVolumeView,
    SettingsView,
)


class Response:
    def __init__(self) -> None:
        self.messages: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def is_done(self) -> bool:
        return False

    async def send_message(self, *args: object, **kwargs: object) -> None:
        self.messages.append((args, kwargs))


def interaction(*, manager: bool = False):
    return SimpleNamespace(
        guild=SimpleNamespace(id=1, voice_client=None),
        channel=SimpleNamespace(id=2),
        user=SimpleNamespace(
            id=3,
            voice=SimpleNamespace(channel=SimpleNamespace(id=4)),
            roles=(),
            guild_permissions=SimpleNamespace(manage_guild=manager),
        ),
        response=Response(),
    )


class MusicStub:
    def __init__(self) -> None:
        self.player = GuildPlayer(1)
        self.player.enqueue(Track("current", "https://example.test", 3))

    async def play(self, _context, _query):
        return Track("queued", "https://example.test", 3)

    async def resolve_track(self, _context, _query):
        return Track("result", "https://example.test", 3)

    async def pause(self, _context):
        pass

    async def resume(self, _context):
        pass

    async def skip(self, _context):
        return None

    async def stop(self, _context):
        pass

    async def seek(self, _context, seconds):
        return seconds

    async def disconnect(self, _context):
        pass

    async def connect(self, _context):
        pass

    async def set_volume(self, _context, value):
        return value

    async def set_loop_mode(self, _context, mode):
        return LoopMode(mode)

    async def player_state(self, _guild_id):
        return self.player

    async def remove_from_queue(self, _context, _index):
        return Track("removed", "https://example.test", 3)

    async def move_in_queue(self, _context, _source, _target):
        pass

    async def shuffle_queue(self, _context):
        pass

    async def clear_queue(self, _context):
        return 2


class SettingsStub:
    def __init__(self) -> None:
        self.settings = GuildSettings(guild_id=1)

    async def update(self, _guild_id, **kwargs):
        section = kwargs["section"]
        values = kwargs["values"]
        self.settings = GuildSettings.model_validate(
            self.settings.model_copy(
                update={
                    section: getattr(self.settings, section).model_copy(update=values)
                }
            ).model_dump()
        )
        return self.settings

    async def get(self, _guild_id):
        return self.settings


def test_music_commands_delegate_to_music_service() -> None:
    async def scenario() -> None:
        service = MusicStub()
        settings = SettingsStub()
        history = SimpleNamespace(
            recent=lambda _guild_id, _limit: asyncio.sleep(0, result=[])
        )
        cog = MusicCog(service, history, settings)  # type: ignore[arg-type]

        await cog.play.callback(cog, interaction(), "query")
        await cog.search.callback(cog, interaction(), "query")
        await cog.pause.callback(cog, interaction())
        await cog.resume.callback(cog, interaction())
        await cog.skip.callback(cog, interaction())
        await cog.stop.callback(cog, interaction())
        await cog.seek.callback(cog, interaction(), 12)
        await cog.leave.callback(cog, interaction())
        await cog.join.callback(cog, interaction())
        await cog.volume.callback(cog, interaction(), 80)
        await cog.loop.callback(cog, interaction(), SimpleNamespace(value="track"))
        await cog.queue.callback(cog, interaction())
        await cog.nowplaying.callback(cog, interaction())
        await cog.autoplay.callback(cog, interaction(), True)
        await cog.history.callback(cog, interaction(), 5)
        await cog.remove.callback(cog, interaction(), 0)
        await cog.move.callback(cog, interaction(), 0, 1)
        await cog.shuffle.callback(cog, interaction())
        await cog.clear.callback(cog, interaction())

    asyncio.run(scenario())


class MemoryStub:
    async def count_user(self, **_kwargs):
        return 2

    async def forget(self, **_kwargs):
        return 1

    async def clear_channel(self, **_kwargs):
        if not _kwargs["can_manage_guild"]:
            raise PermissionDeniedError("Manage Server permission is required")
        return 1

    async def clear_user(self, **_kwargs):
        return 1


def test_memory_and_admin_commands_render_safe_responses() -> None:
    async def scenario() -> None:
        memory = MemoryCog(MemoryStub(), SettingsStub())  # type: ignore[arg-type]
        status = interaction(manager=True)
        await memory.status.callback(memory, status)
        await memory.stats.callback(memory, interaction(manager=True))
        await memory.forget.callback(memory, interaction(), "memory")
        await memory.clear_channel.callback(memory, interaction(manager=True), 2)
        await memory.clear_user.callback(memory, interaction(manager=True), 4)
        assert status.response.messages

        roles = SimpleNamespace(
            add_role=lambda *args: asyncio.sleep(0),
            remove_role=lambda *args: asyncio.sleep(0, result=True),
            list_roles=lambda *args: asyncio.sleep(0, result=[(5, "DJ")]),
        )
        dj = DJCog(roles)
        for command in (dj.add, dj.remove, dj.list):
            assert command is not None

    asyncio.run(scenario())


def test_settings_and_playlist_adapters_construct_with_services() -> None:
    assert SettingsCog(SettingsStub())
    assert PlaylistCog(object())


def test_chat_adapter_filters_messages_and_sends_reactions() -> None:
    class AgentStub:
        async def get_settings(self, _guild_id):
            return GuildSettings(guild_id=1)

        async def handle(self, *_args, **_kwargs):
            return PeaceMusicState(
                request_id="req",
                guild_id=1,
                channel_id=2,
                user_id=3,
                final_response="hello",
            )

    class Typing:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    async def scenario() -> None:
        sent: list[str] = []
        reactions: list[str] = []
        channel = SimpleNamespace(
            id=2,
            typing=lambda: Typing(),
            send=lambda text: asyncio.sleep(0, result=sent.append(text)),
        )
        message = SimpleNamespace(
            author=SimpleNamespace(
                bot=False,
                id=3,
                display_name="User",
                voice=None,
                guild_permissions=SimpleNamespace(manage_guild=False),
            ),
            guild=SimpleNamespace(id=1),
            channel=channel,
            content="hello",
            mentions=(),
            attachments=(),
            add_reaction=lambda emoji: asyncio.sleep(0, result=reactions.append(emoji)),
        )
        await ChatCog(AgentStub()).on_message(message)
        assert sent == ["hello"]
        assert reactions == ["🤖"]

    asyncio.run(scenario())


def test_dj_and_playlist_commands_delegate() -> None:
    class Roles:
        async def add_role(self, *_args):
            pass

        async def remove_role(self, *_args):
            return True

        async def list_roles(self, *_args):
            return [(9, "DJ")]

    class Role:
        id = 9
        name = "DJ"

    class Playlists:
        async def create(self, *_args):
            return Playlist(id=1, guild_id=1, owner_user_id=3, name="mix")

        async def delete(self, *_args):
            pass

        async def add(self, *_args):
            return Playlist(
                id=1,
                guild_id=1,
                owner_user_id=3,
                name="mix",
                tracks=(PlaylistTrack(title="song", source_url="url"),),
            )

        async def remove(self, *_args):
            return Track("song", "url", 3)

        async def play(self, *_args):
            return 1

        async def list(self, *_args):
            return []

    async def scenario() -> None:
        manager = interaction(manager=True)
        manager.guild.get_role = lambda _role_id: Role()
        dj = DJCog(Roles())
        await dj.add.callback(dj, manager, 9)
        await dj.remove.callback(dj, manager, 9)
        await dj.list.callback(dj, manager)

        playlist = PlaylistCog(Playlists())
        await playlist.create.callback(playlist, interaction(), "mix")
        await playlist.delete.callback(playlist, interaction(), "mix")
        await playlist.add.callback(playlist, interaction(), "mix", "song")
        await playlist.remove.callback(playlist, interaction(), "mix", 0)
        await playlist.play.callback(playlist, interaction(), "mix")
        await playlist.list.callback(playlist, interaction())

    asyncio.run(scenario())


def test_settings_wizard_persists_each_configuration_step() -> None:
    class EditResponse(Response):
        async def edit_message(self, **kwargs: object) -> None:
            self.messages.append(((), kwargs))

    class DJRoles:
        async def add_role(self, *_args):
            pass

    async def scenario() -> None:
        service = SettingsStub()
        response = EditResponse()
        current = SimpleNamespace(response=response)
        setup = SetupView(service, guild_id=1, actor_user_id=3)
        await setup.on_channel_selected(current, SimpleNamespace(id=10))
        ai_channel = AIChannelSetupView(
            service, guild_id=1, actor_user_id=3, dj_roles=DJRoles()
        )
        await ai_channel.on_channel_selected(current, SimpleNamespace(id=11))
        ai = AISetupView(service, guild_id=1, actor_user_id=3, dj_roles=DJRoles())
        await ai._finish(current, enabled=True)
        mention = SetupMentionView(
            service, guild_id=1, actor_user_id=3, dj_roles=DJRoles()
        )
        await mention._finish(current, required=True)
        dj = SetupDJRoleView(service, guild_id=1, actor_user_id=3, dj_roles=DJRoles())
        await dj.on_role_selected(current, SimpleNamespace(id=12, name="DJ"))
        volume = SetupVolumeView(service, guild_id=1, actor_user_id=3)
        await volume._finish(current, 80)
        autoplay = SetupAutoplayView(service, guild_id=1, actor_user_id=3)
        await autoplay._finish(current, enabled=True)

        settings = SettingsView(service, guild_id=1, actor_user_id=3)
        await settings.show_section(current, "memory")
        await settings._toggle(current, "ai", "enabled")
        await settings._toggle(current, "memory", "enabled")
        await settings.show_section(current, "not-a-section")
        assert len(response.messages) >= 9

    asyncio.run(scenario())
