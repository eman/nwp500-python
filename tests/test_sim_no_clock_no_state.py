"""The simulator core reads no clock and holds no mutable module state.

**No clock.** No module of ``nwp500.sim`` calls ``datetime.now``,
``datetime.utcnow``, ``date.today``, or the ``time`` module's
``time``, ``monotonic``, ``perf_counter``, ``time_ns`` or
``monotonic_ns``, however it was imported: the instant a walk starts
at is its caller's input, so a scenario replays identically.

**No mutable module state.** Nothing at a module's top level (inside
a top-level ``if`` or ``try`` too), or in a class body, is bound to a
list, dict or set (a display, a comprehension or a constructor call);
no function rebinds a module's name (``global``); and none is a cache
(``functools.cache``, ``lru_cache``), which keeps its answers in the
module. A table the core keeps is read-only: a ``tuple``, a
``frozenset``, a ``MappingProxyType``. Held twice, as the import
contract is: by reading the source, and by importing every module and
looking at what its names are bound to, which also sees a numpy array
left writeable.
"""

import ast
import dataclasses
import importlib
import pkgutil
import types
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import nwp500.sim

SIM_ROOT = Path(nwp500.sim.__file__).parent
SOURCES = sorted(SIM_ROOT.rglob("*.py"))
IDS = [p.relative_to(SIM_ROOT).as_posix() for p in SOURCES]

#: Methods that read the clock, called on anything (``datetime.now``,
#: ``datetime.utcnow``, ``date.today``, and the same of an alias).
CLOCK_METHODS = frozenset({"now", "utcnow", "today"})
#: The ``time`` module's clocks, called as ``time.time()`` or imported
#: by name.
TIME_CLOCKS = frozenset(
    {
        "time",
        "monotonic",
        "perf_counter",
        "time_ns",
        "monotonic_ns",
    }
)
#: Decorators that keep a function's answers in the module.
CACHES = frozenset({"cache", "lru_cache"})

#: Constructors of a mutable container.
MUTABLE_CALLS = frozenset(
    {
        "list",
        "dict",
        "set",
        "bytearray",
        "defaultdict",
        "OrderedDict",
        "Counter",
        "deque",
    }
)
MUTABLE_DISPLAYS = (
    ast.List,
    ast.Dict,
    ast.Set,
    ast.ListComp,
    ast.DictComp,
    ast.SetComp,
)


def _dotted(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    return ""


def _clock_reads(source: str) -> list[tuple[int, str]]:
    """Every clock ``source`` reads, with its line."""
    tree = ast.parse(source)
    # ``from time import time, monotonic`` (aliased or not): the local
    # names they are bound to.
    by_name = {
        a.asname or a.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "time"
        for a in node.names
        if a.name in TIME_CLOCKS
    }
    # ``import time as t``: the module's local names.
    modules = {"time"} | {
        a.asname or a.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for a in node.names
        if a.name == "time"
    }
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            if func.attr in CLOCK_METHODS or (
                func.attr in TIME_CLOCKS and _dotted(func.value) in modules
            ):
                found.append((node.lineno, _dotted(func) or func.attr))
        elif isinstance(func, ast.Name) and func.id in by_name:
            found.append((node.lineno, func.id))
    return found


def _mutable_value(value: ast.expr | None) -> bool:
    if value is None:
        return False
    if isinstance(value, MUTABLE_DISPLAYS):
        return True
    return (
        isinstance(value, ast.Call)
        and _dotted(value.func).rpartition(".")[2] in MUTABLE_CALLS
    )


def _bindings(body: list[ast.stmt]) -> list[tuple[int, str, ast.expr | None]]:
    out: list[tuple[int, str, ast.expr | None]] = []
    for node in body:
        if isinstance(node, ast.Assign):
            out.extend(
                (node.lineno, ast.unparse(t), node.value) for t in node.targets
            )
        elif isinstance(node, ast.AnnAssign | ast.AugAssign):
            out.append((node.lineno, ast.unparse(node.target), node.value))
        elif isinstance(node, ast.ClassDef):
            out.extend(_bindings(node.body))
        elif isinstance(node, ast.If):
            out.extend(_bindings(node.body))
            out.extend(_bindings(node.orelse))
        elif isinstance(node, ast.Try | ast.TryStar):
            out.extend(_bindings(node.body))
            for handler in node.handlers:
                out.extend(_bindings(handler.body))
            out.extend(_bindings(node.orelse))
            out.extend(_bindings(node.finalbody))
    return out


def _cached(node: ast.AST) -> list[tuple[int, str]]:
    """Every function under ``node`` decorated as a cache."""
    found = []
    for fn in ast.walk(node):
        if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for d in fn.decorator_list:
            target = d.func if isinstance(d, ast.Call) else d
            name = _dotted(target).rpartition(".")[2]
            if name in CACHES:
                found.append((fn.lineno, f"@{name} {fn.name}"))
    return found


def _mutable_state(source: str) -> list[tuple[int, str]]:
    """Every mutable binding at ``source``'s top level or in a class
    body, and every ``global`` statement, with its line. A dataclass's
    ``field(default_factory=list)`` is per instance and is not one."""
    tree = ast.parse(source)
    found = [
        (line, name)
        for line, name, value in _bindings(tree.body)
        if _mutable_value(value)
    ]
    found += [
        (node.lineno, f"global {', '.join(node.names)}")
        for node in ast.walk(tree)
        if isinstance(node, ast.Global)
    ]
    found += _cached(tree)
    return sorted(found)


@pytest.mark.parametrize("path", SOURCES, ids=IDS)
def test_no_source_reads_the_clock(path: Path) -> None:
    bad = [f"{path.name}:{n}: {c}" for n, c in _clock_reads(path.read_text())]
    assert not bad, "the core reads the clock:\n" + "\n".join(bad)


@pytest.mark.parametrize("path", SOURCES, ids=IDS)
def test_no_source_holds_mutable_module_state(path: Path) -> None:
    bad = [f"{path.name}:{n}: {w}" for n, w in _mutable_state(path.read_text())]
    assert not bad, "the core holds mutable state:\n" + "\n".join(bad)


def test_the_clock_check_sees_a_violation() -> None:
    """Each clock is found, however it was imported, and arithmetic on
    a value named ``now`` is not a read."""
    source = (
        "import time\n"
        "import time as clock\n"
        "from time import monotonic\n"
        "from time import time as wall\n"
        "from datetime import date, datetime\n"
        "a = datetime.now(tz=UTC)\n"
        "b = datetime.utcnow()\n"
        "c = date.today()\n"
        "d = time.time()\n"
        "e = clock.monotonic()\n"
        "f = monotonic()\n"
        "g = wall()\n"
        "h = pd.Timestamp.now()\n"
        "i = (target - now).total_seconds()\n"
        "j = time.perf_counter_ns  # not called\n"
        "from time import monotonic_ns\n"
        "k = time.perf_counter()\n"
        "m = clock.time_ns()\n"
        "n = monotonic_ns()\n"
    )
    assert [c for _, c in _clock_reads(source)] == [
        "datetime.now",
        "datetime.utcnow",
        "date.today",
        "time.time",
        "clock.monotonic",
        "monotonic",
        "wall",
        "pd.Timestamp.now",
        "time.perf_counter",
        "clock.time_ns",
        "monotonic_ns",
    ]


def test_the_state_check_sees_a_violation() -> None:
    """Each mutable binding is found, at the top level and in a class
    body, as is a ``global``; read-only tables and per-instance
    defaults are not."""
    source = (
        "A = []\n"
        "B: dict[str, int] = {}\n"
        "C = {1, 2}\n"
        "D = [x for x in range(3)]\n"
        "E = {k: k for k in 'ab'}\n"
        "F = defaultdict(list)\n"
        "G = collections.deque()\n"
        "H: Final = dict(a=1)\n"
        "class K:\n"
        "    cache = {}\n"
        "    xs: list[int] = field(default_factory=list)\n"
        "def f():\n"
        "    global A\n"
        "    local = []\n"
        "OK1 = (1, 2)\n"
        "OK2 = frozenset({1})\n"
        "OK3: Final = MappingProxyType({'a': 1})\n"
        "OK4 = tuple(x for x in range(3))\n"
        "if TYPE_CHECKING:\n"
        "    I = []\n"
        "else:\n"
        "    J = {}\n"
        "try:\n"
        "    L = set()\n"
        "except ImportError:\n"
        "    M = []\n"
        "finally:\n"
        "    N = {}\n"
        "@functools.cache\n"
        "def p(): ...\n"
        "@lru_cache(maxsize=8)\n"
        "def q(): ...\n"
        "class R:\n"
        "    @functools.lru_cache\n"
        "    def s(self): ...\n"
        "@property\n"
        "def ok5(): ...\n"
    )
    assert [w for _, w in _mutable_state(source)] == [
        "A",
        "B",
        "C",
        "D",
        "E",
        "F",
        "G",
        "H",
        "cache",
        "global A",
        "I",
        "J",
        "L",
        "M",
        "N",
        "@cache p",
        "@lru_cache q",
        "@lru_cache s",
    ]


def _modules() -> list[types.ModuleType]:
    names = ["nwp500.sim"] + [
        m.name
        for m in pkgutil.walk_packages(
            nwp500.sim.__path__, prefix="nwp500.sim."
        )
    ]
    return [importlib.import_module(n) for n in names]


def _mutable(value: object) -> bool:
    """Whether ``value`` is a container that can be changed in place."""
    if isinstance(value, np.ndarray):
        return bool(value.flags.writeable)
    if isinstance(
        value, list | dict | set | bytearray | pd.Series | pd.DataFrame
    ):
        return True
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return not type(value).__dataclass_params__.frozen  # type: ignore[attr-defined]
    return False


def test_no_module_is_bound_to_a_mutable_value() -> None:
    bad = [
        f"{module.__name__}.{name}: {type(value).__name__}"
        for module in _modules()
        for name, value in vars(module).items()
        if not name.startswith("__") and _mutable(value)
    ]
    assert not bad, "the core holds mutable state:\n" + "\n".join(bad)


def test_the_value_check_sees_a_violation() -> None:
    @dataclasses.dataclass
    class Loose:
        x: int = 0

    @dataclasses.dataclass(frozen=True)
    class Frozen:
        x: int = 0

    sealed = np.zeros(3)
    sealed.setflags(write=False)
    values: tuple[object, ...] = (
        [],
        {},
        set(),
        np.zeros(3),
        pd.Series(dtype=float),
        Loose(),
        (),
        frozenset(),
        types.MappingProxyType({}),
        sealed,
        sealed[:1],
        Frozen(),
    )
    assert [_mutable(v) for v in values] == [True] * 6 + [False] * 6
