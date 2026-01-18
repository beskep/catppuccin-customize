import dataclasses as dc
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import catppuccin
import coloraide
import cyclopts
import msgspec
from coloraide.spaces.okhsl import Okhsl

if TYPE_CHECKING:
    from collections.abc import Sequence

    from catppuccin import models


class _Color(coloraide.Color): ...


_Color.register(Okhsl())


@dc.dataclass(frozen=True)
class _Edit:
    variable: str
    value: float
    type: Literal['value', 'multiply'] = 'value'

    name: str | None = None
    accent: bool | None = None

    def __call__(self, value: float) -> float:
        match self.type:
            case 'value':
                return self.value
            case 'multiply':
                v = self.value
                return value * v
            case _:
                raise ValueError(self.type)


@dc.dataclass(frozen=True)
class _Colors:
    name: str
    original: str
    custom: str
    changed: bool

    @classmethod
    def create(cls, color: models.Color, edits: Sequence[_Edit]):
        c = _Color(color.hex).convert('okhsl')

        for edit in edits:
            if (
                edit.name in {color.name, color.identifier}
                or edit.accent == color.accent
            ):
                c.set(edit.variable, edit)

        custom = c.convert('srgb').to_string(hex=True)

        return cls(
            name=color.identifier,
            original=color.hex,
            custom=custom,
            changed=color.hex != custom,
        )


@dc.dataclass(frozen=True)
class _Flavor:
    name: str
    colors: tuple[_Colors, ...]

    @classmethod
    def create(cls, flavor: models.Flavor, edits: Sequence[_Edit]):
        return cls(
            name=flavor.identifier,
            colors=tuple(_Colors.create(c, edits) for c in flavor.colors),
        )

    def original(self):
        return {c.name: c.original for c in self.colors}

    def custom(self):
        return {c.name: c.custom for c in self.colors}

    def dict(self):
        return {c.original: c.custom for c in self.colors if c.changed}


def _write(obj: Any, path: Path):
    path.with_suffix('.toml').write_bytes(msgspec.toml.encode(obj))

    buf = msgspec.json.encode(obj)
    buf = msgspec.json.format(buf)
    path.with_suffix('.json').write_bytes(buf)


app = cyclopts.App(
    help_on_error=True,
    result_action=['call_if_callable', 'print_non_int_sys_exit'],
)


@app.default
@dc.dataclass
class Editor:
    conf: str = 'config.toml'

    @cached_property
    def edits(self):
        return msgspec.toml.decode(
            Path(self.conf).read_bytes(),
            type=dict[str, tuple[_Edit, ...]],
        )

    @cached_property
    def palette(self) -> dict[str, _Flavor]:
        return {
            flavor.identifier: _Flavor.create(
                flavor, self.edits['dark' if flavor.dark else 'light']
            )
            for flavor in catppuccin.PALETTE
        }

    def __call__(self):
        _write(
            {k: v.original() for k, v in self.palette.items()},
            Path('palette-original.toml'),
        )
        _write(
            {k: v.custom() for k, v in self.palette.items()},
            Path('palette-custom.toml'),
        )
        _write(
            {k: v.dict() for k, v in self.palette.items()},
            Path('palette-dict.toml'),
        )


@app.command
@dc.dataclass
class Replace:
    src: Path
    dst: Path | None = None
    conf: str = 'config.toml'

    def _dst(self):
        dst = self.dst or self.src.with_stem(f'{self.src.stem}-replaced')
        if dst.exists():
            raise FileExistsError(dst)
        return dst

    def _colors(self):
        palette = Editor(self.conf).palette

        for flavor in palette.values():
            yield from flavor.dict().items()

    def __call__(self):
        dst = self._dst()
        colors = dict(self._colors())

        text = self.src.read_text()
        for prev, new in colors.items():
            text = text.replace(prev, new)

        dst.write_text(text)


if __name__ == '__main__':
    app()
