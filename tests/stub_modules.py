from __future__ import annotations

import importlib.util
import importlib
import math
import struct
import sys
import types as py_types
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class FakeVector:
    def __init__(self, values):
        self.data = [float(value) for value in values]

    @property
    def size(self) -> int:
        return len(self.data)

    @property
    def shape(self) -> tuple[int]:
        return (len(self.data),)

    def __iter__(self):
        return iter(self.data)

    def __len__(self) -> int:
        return len(self.data)

    def __getitem__(self, item):
        if isinstance(item, slice):
            return FakeVector(self.data[item])
        if isinstance(item, FakeVector):
            item = item.data
        if isinstance(item, (list, tuple)):
            return FakeVector([self.data[int(index)] for index in item])
        return self.data[int(item)]

    def __truediv__(self, scalar: float) -> "FakeVector":
        return FakeVector([value / scalar for value in self.data])

    def __mul__(self, other):
        if isinstance(other, FakeVector):
            return FakeVector([a * b for a, b in zip(self.data, other.data)])
        return FakeVector([value * other for value in self.data])

    def tobytes(self) -> bytes:
        if not self.data:
            return b""
        return struct.pack("<" + "f" * len(self.data), *self.data)


class FakeMatrix:
    def __init__(self, rows):
        self.rows = [
            row if isinstance(row, FakeVector) else FakeVector(row) for row in rows
        ]

    def __matmul__(self, vector: FakeVector) -> FakeVector:
        return FakeVector(
            sum(left * right for left, right in zip(row.data, vector.data))
            for row in self.rows
        )


def _install_numpy_stub() -> None:
    numpy_module = py_types.ModuleType("numpy")

    def asarray(values, dtype=None):
        if isinstance(values, FakeVector):
            return FakeVector(values.data)
        return FakeVector(values)

    def ascontiguousarray(values, dtype=None):
        if isinstance(values, FakeVector):
            return FakeVector(values.data)
        return asarray(values, dtype=dtype)

    def frombuffer(raw_bytes, dtype=None):
        if not raw_bytes:
            return FakeVector([])
        count = len(raw_bytes) // 4
        unpacked = struct.unpack("<" + "f" * count, raw_bytes)
        return FakeVector(unpacked)

    def vstack(vectors):
        return FakeMatrix(vectors)

    def argpartition(values, kth):
        vector = values if isinstance(values, FakeVector) else FakeVector(values)
        return FakeVector(
            sorted(range(len(vector.data)), key=lambda index: vector.data[index])
        )

    def argsort(values):
        vector = values if isinstance(values, FakeVector) else FakeVector(values)
        return FakeVector(
            sorted(range(len(vector.data)), key=lambda index: vector.data[index])
        )

    def power(base, exponent):
        if isinstance(exponent, FakeVector):
            return FakeVector([math.pow(base, exp) for exp in exponent.data])
        return math.pow(base, exponent)

    numpy_module.asarray = asarray
    numpy_module.ascontiguousarray = ascontiguousarray
    numpy_module.frombuffer = frombuffer
    numpy_module.vstack = vstack
    numpy_module.argpartition = argpartition
    numpy_module.argsort = argsort
    numpy_module.power = power
    numpy_module.float32 = float
    numpy_module.ndarray = FakeVector
    numpy_module.linalg = SimpleNamespace(
        norm=lambda vector: math.sqrt(sum(value * value for value in vector.data))
    )
    sys.modules["numpy"] = numpy_module


def _install_discord_stub() -> None:
    discord_module = py_types.ModuleType("discord")
    app_commands_module = py_types.ModuleType("discord.app_commands")
    discord_ext_module = py_types.ModuleType("discord.ext")
    commands_module = py_types.ModuleType("discord.ext.commands")
    tasks_module = py_types.ModuleType("discord.ext.tasks")

    class Intents:
        @classmethod
        def default(cls):
            return cls()

        @classmethod
        def all(cls):
            return cls()

    class Cog:
        @classmethod
        def listener(cls):
            def decorator(func):
                return func

            return decorator

    class Bot:
        pass

    class AudioSource:
        def read(self):
            return b""

        def cleanup(self):
            return None

    class PCMVolumeTransformer(AudioSource):
        def __init__(self, original, volume=1.0):
            self.original = original
            self.volume = volume

        def read(self):
            return self.original.read()

        def cleanup(self):
            return self.original.cleanup()

    class FFmpegPCMAudio(AudioSource):
        def __init__(self, source, **kwargs):
            self.source = source
            self.options = kwargs

    class Color:
        @classmethod
        def purple(cls):
            return cls()

        @classmethod
        def green(cls):
            return cls()

        @classmethod
        def blue(cls):
            return cls()

    class _Loop:
        def __init__(self, coro):
            self.coro = coro

        def __get__(self, instance, owner):
            return self

        def start(self):
            return None

        def cancel(self):
            return None

        def before_loop(self, func):
            return func

    def _loop_decorator(**kwargs):
        def decorator(func):
            return _Loop(func)

        return decorator

    class Choice:
        def __init__(self, *, name, value):
            self.name = name
            self.value = value

        @classmethod
        def __class_getitem__(cls, item):
            return cls

    def _identity_decorator(*args, **kwargs):
        def decorator(func):
            return func

        return decorator

    class _ChecksNamespace:
        @staticmethod
        def has_permissions(**kwargs):
            return _identity_decorator

    app_commands_module.Choice = Choice
    app_commands_module.command = _identity_decorator
    app_commands_module.describe = _identity_decorator
    app_commands_module.choices = _identity_decorator
    app_commands_module.default_permissions = _identity_decorator
    app_commands_module.guild_only = _identity_decorator
    app_commands_module.checks = _ChecksNamespace()

    discord_module.Intents = Intents
    discord_module.AudioSource = AudioSource
    discord_module.PCMVolumeTransformer = PCMVolumeTransformer
    discord_module.FFmpegPCMAudio = FFmpegPCMAudio
    discord_module.VoiceClient = type("VoiceClient", (), {})
    discord_module.Color = Color
    discord_module.Embed = type("Embed", (), {})
    discord_module.VoiceState = type("VoiceState", (), {})
    discord_module.Message = type("Message", (), {})
    discord_module.Attachment = type("Attachment", (), {})
    discord_module.Member = type("Member", (), {})
    discord_module.Interaction = type("Interaction", (), {})
    discord_module.HTTPException = type("HTTPException", (Exception,), {})
    discord_module.app_commands = app_commands_module
    commands_module.Cog = Cog
    commands_module.Bot = Bot
    tasks_module.loop = _loop_decorator
    discord_ext_module.commands = commands_module
    discord_ext_module.tasks = tasks_module
    discord_module.ext = discord_ext_module
    sys.modules["discord.app_commands"] = app_commands_module
    sys.modules["discord"] = discord_module
    sys.modules["discord.ext"] = discord_ext_module
    sys.modules["discord.ext.commands"] = commands_module
    sys.modules["discord.ext.tasks"] = tasks_module


def _install_google_stub() -> None:
    google_module = py_types.ModuleType("google")
    genai_module = py_types.ModuleType("google.genai")
    types_module = py_types.ModuleType("google.genai.types")
    errors_module = py_types.ModuleType("google.genai.errors")

    class ThinkingConfig:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class GenerateContentConfig:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class EmbedContentConfig:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class HttpOptions:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FunctionCall:
        def __init__(self, name="", args=None, id=None):
            self.name = name
            self.args = args or {}
            self.id = id

    class FunctionResponse:
        def __init__(self, name="", response=None, id=None):
            self.name = name
            self.response = response or {}
            self.id = id

    class FileData:
        def __init__(self, uri="", mime_type=None):
            self.uri = uri
            self.mime_type = mime_type

    class Part:
        def __init__(
            self,
            *,
            text=None,
            file_data=None,
            function_call=None,
            function_response=None,
        ):
            self.text = text
            self.file_data = file_data
            self.function_call = function_call
            self.function_response = function_response

        @classmethod
        def from_text(cls, text: str):
            return cls(text=text)

        @classmethod
        def from_uri(cls, file_uri: str, mime_type=None):
            return cls(file_data=FileData(uri=file_uri, mime_type=mime_type))

        @classmethod
        def from_function_call(cls, name: str, args=None):
            return cls(function_call=FunctionCall(name=name, args=args or {}))

        @classmethod
        def from_function_response(cls, name: str, response=None):
            return cls(
                function_response=FunctionResponse(name=name, response=response or {})
            )

    class Content:
        def __init__(self, role: str, parts):
            self.role = role
            self.parts = list(parts)

    class Candidate:
        def __init__(self, content=None):
            self.content = content

    class GenerateContentResponse:
        def __init__(self, *, candidates=None, text=None):
            self.candidates = candidates or []
            self.text = text

    class File:
        def __init__(self, name="", uri="", mime_type=None, state=None):
            self.name = name
            self.uri = uri
            self.mime_type = mime_type
            self.state = state

    class Tool:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FunctionDeclaration:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class Schema:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class Type:
        OBJECT = "object"
        STRING = "string"
        NUMBER = "number"
        INTEGER = "integer"

    types_module.ThinkingConfig = ThinkingConfig
    types_module.GenerateContentConfig = GenerateContentConfig
    types_module.EmbedContentConfig = EmbedContentConfig
    types_module.HttpOptions = HttpOptions
    types_module.FunctionCall = FunctionCall
    types_module.FunctionResponse = FunctionResponse
    types_module.Part = Part
    types_module.Content = Content
    types_module.Candidate = Candidate
    types_module.GenerateContentResponse = GenerateContentResponse
    types_module.File = File
    types_module.Tool = Tool
    types_module.FunctionDeclaration = FunctionDeclaration
    types_module.Schema = Schema
    types_module.Type = Type

    class ServerError(Exception):
        pass

    errors_module.ServerError = ServerError
    genai_module.types = types_module
    genai_module.errors = errors_module
    google_module.genai = genai_module

    sys.modules["google"] = google_module
    sys.modules["google.genai"] = genai_module
    sys.modules["google.genai.types"] = types_module
    sys.modules["google.genai.errors"] = errors_module


def install_stubs() -> None:
    _install_numpy_stub()
    _install_discord_stub()
    _install_google_stub()


def load_project_module(module_name: str, relative_path: str):
    module_path = PROJECT_ROOT / relative_path
    if module_name in sys.modules:
        del sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def import_project_package(module_name: str):
    project_root_str = str(PROJECT_ROOT)
    if project_root_str not in sys.path:
        sys.path.insert(0, project_root_str)
    if module_name in sys.modules:
        del sys.modules[module_name]
    return importlib.import_module(module_name)
