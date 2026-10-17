"""The simulator core's import contract.

``nwp500.sim`` performs no I/O: it imports nothing from the rest of
``nwp500`` (so neither the MQTT nor the REST client, nor the
authentication), and nothing of aiohttp or the AWS IoT SDK. numpy and
pandas are allowed. Nor does it hold per-request state (no
``ContextVar`` or thread), and it does not log: what it would warn of
is in its result. It could therefore be split into its own
distribution with no change to its code.

``import nwp500`` never loads it: the simulator is optional, behind the
``sim`` extra.

The core models the heater, not what drives it or what it is plumbed
into: it knows no control integration (no plan, segment or capability
declaration) and no pump, loop or recirculation. Water moves through
the tank only as draws, each with the temperature of the water
replacing it; what a draw stands for is the caller's. Not as a name, a
comment or a docstring; the heat pump, the heater's own, is not a pump
in this sense.

The imports are held by reading every import statement in the
package's source, function-local and ``TYPE_CHECKING`` ones included.
"""

import ast
import io
import json
import os
import re
import subprocess
import sys
import tokenize
from pathlib import Path

import pytest

SIM_ROOT = Path(__file__).parents[1] / "src" / "nwp500" / "sim"
SOURCES = sorted(SIM_ROOT.rglob("*.py"))
IDS = [p.relative_to(SIM_ROOT).as_posix() for p in SOURCES]

#: Top-level packages the core must never import: the network clients.
FORBIDDEN = frozenset({"aiohttp", "awscrt", "awsiot"})

#: Per-request state, and logging: the core is the same on every
#: thread, writes to no handler, and returns what it would warn of.
#: Refused in its source only, since numpy and pandas load all three.
STATEFUL = frozenset({"contextvars", "threading", "logging"})

#: A control integration's vocabulary: names the core's code must not
#: use, matched exactly, and fragments no name of it may contain,
#: whatever its case. ``typing.Protocol`` is Python's, not a control
#: protocol, and is not matched.
ADAPTER_NAMES = frozenset(
    {
        "Plan",
        "PlanResult",
        "PlanStatus",
        "Capabilities",
        "protocols",
        "programmed_until",
    }
)
ADAPTER_FRAGMENTS = (
    "segment",
    "capabilit",
    "reassert",
    "near_term",
    "protocol_version",
    "realise_plan",
    "entry_limit",
    "entry_reserve",
    "owner_entries",
    "horizon_h",
    "program_scheduled",
)

#: Words the core's text may not contain, comments and docstrings
#: included: it models the heater, not the integration that drives it,
#: nor a meter or pump by brand.
OFF_TOPIC = re.compile(r"ha[_-]nwp500|\badapter|droplet|grundfos", re.I)

#: Plumbing: a pump, a loop or recirculation, as a name or in text,
#: whatever its case. A heat pump (``heat pump``, ``heat-pump``,
#: ``HEAT_PUMP``, ``HeatPump``) is the heater's own and is not matched.
PLUMBING = re.compile(r"(?<!heat)(?<!heat[ _-])pump|loop|recirc", re.I)


def _module_name(path: Path) -> str:
    rel = path.relative_to(SIM_ROOT.parent.parent).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imports(path: Path) -> list[tuple[int, str]]:
    """Every module ``path`` imports, absolute, with its line."""
    tree = ast.parse(path.read_text(), filename=str(path))
    package = _module_name(path)
    if path.name != "__init__.py":
        package = package.rpartition(".")[0]
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, a.name) for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                base = base[: len(base) - (node.level - 1)]
                module = ".".join([*base, node.module] if node.module else base)
            else:
                module = node.module or ""
            found.append((node.lineno, module))
    return found


def _violation(module: str) -> bool:
    top = module.split(".")[0]
    if top in FORBIDDEN or top in STATEFUL:
        return True
    if top == "nwp500":
        return not (module == "nwp500.sim" or module.startswith("nwp500.sim."))
    return False


def _adapter_names(source: str) -> list[tuple[int, str]]:
    """Every name in ``source``'s code that is a control integration's
    (``ADAPTER_NAMES``, ``ADAPTER_FRAGMENTS``), with its line:
    identifiers, not words in a docstring or comment."""
    found = []
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type != tokenize.NAME:
            continue
        low = tok.string.lower()
        if tok.string in ADAPTER_NAMES or any(
            f in low for f in ADAPTER_FRAGMENTS
        ):
            found.append((tok.start[0], tok.string))
    return found


def _matches(pattern: re.Pattern[str], text: str) -> list[tuple[int, str]]:
    return [
        (n, m.group(0))
        for n, line in enumerate(text.splitlines(), 1)
        for m in pattern.finditer(line)
    ]


def test_the_core_has_modules_to_check():
    names = set(IDS)
    assert {
        "params.py",
        "units.py",
        "physics/compressor.py",
        "tank_physics.py",
        "decay.py",
        "heating_trajectory.py",
        "recovery.py",
        "extensions.py",
        "controller.py",
        "tou_triggers.py",
        "engine.py",
    } <= names


@pytest.mark.parametrize("path", SOURCES, ids=IDS)
def test_no_source_imports_outside_the_core(path: Path):
    bad = [
        f"{path.name}:{line}: {module}"
        for line, module in _imports(path)
        if _violation(module)
    ]
    assert not bad, "the core imports outside itself:\n" + "\n".join(bad)


@pytest.mark.parametrize("path", SOURCES, ids=IDS)
def test_no_source_knows_a_control_adapter(path: Path):
    """The heater takes entries, writes and its TOU switch; a plan's
    segments, an integration's declaration and its protocol are the
    caller's."""
    bad = [
        f"{path.name}:{line}: {name}"
        for line, name in _adapter_names(path.read_text())
    ]
    assert not bad, "the core knows an adapter:\n" + "\n".join(bad)


@pytest.mark.parametrize("path", SOURCES, ids=IDS)
def test_no_source_mentions_the_integration_or_a_brand(path: Path):
    bad = [
        f"{path.name}:{n}: {w}"
        for n, w in _matches(OFF_TOPIC, path.read_text())
    ]
    assert not bad, "the core mentions:\n" + "\n".join(bad)


@pytest.mark.parametrize("path", SOURCES, ids=IDS)
def test_no_source_knows_a_pump_or_a_loop(path: Path):
    """A circulation run is a draw, which the caller makes of it; the
    core has no pump, loop or recirculation concept."""
    bad = [
        f"{path.name}:{n}: {w}" for n, w in _matches(PLUMBING, path.read_text())
    ]
    assert not bad, "the core knows the plumbing:\n" + "\n".join(bad)


def test_the_import_check_sees_a_violation():
    """Each kind of import the check must refuse is refused, and an
    import inside the core, or of numpy and pandas, is not."""
    for module in (
        "nwp500",
        "nwp500.mqtt",
        "nwp500.mqtt.client",
        "nwp500.api_client",
        "nwp500.auth",
        "nwp500.models",
        "nwp500.simulator",
        "aiohttp",
        "awscrt.mqtt",
        "awsiot.mqtt_connection_builder",
        "contextvars",
        "threading",
        "logging",
    ):
        assert _violation(module), module
    for module in (
        "nwp500.sim",
        "nwp500.sim.params",
        "nwp500.sim.physics.tank",
        "math",
        "numpy",
        "pandas",
    ):
        assert not _violation(module), module


def test_the_adapter_check_sees_a_violation():
    """Each concept is found as a name, in any case, and
    ``typing.Protocol`` and words in a docstring or comment are not."""
    source = (
        '"""A segment of a plan, merged and reasserted."""\n'
        "from typing import Protocol\n"
        "# Capabilities and near-term entries are the integration's.\n"
        "class Physics(Protocol): ...\n"
        "def realise_plan(plan: Plan, caps: Capabilities) -> PlanResult:\n"
        "    seg = Segment(reassert=True)\n"
        "    lead = caps.near_term_lead_min + caps.entry_limit\n"
        "    return caps.protocol_versions, caps.horizon_h, SegmentResult\n"
    )
    assert [n for _, n in _adapter_names(source)] == [
        "realise_plan",
        "Plan",
        "Capabilities",
        "PlanResult",
        "Segment",
        "reassert",
        "near_term_lead_min",
        "entry_limit",
        "protocol_versions",
        "horizon_h",
        "SegmentResult",
    ]


def test_the_mention_check_sees_a_violation():
    text = "# as eman/ha_nwp500#158 says\n# the Adapter's names\nx = 1\n"
    text += '"""metered by the Droplet, pumped by a Grundfos"""\n'
    assert [w.lower() for _, w in _matches(OFF_TOPIC, text)] == [
        "ha_nwp500",
        "adapter",
        "droplet",
        "grundfos",
    ]


def test_the_plumbing_check_spares_the_heat_pump():
    """The heater is a heat pump, in any spelling."""
    text = "heat pump, heat-pump, HEAT_PUMP, HeatPump, heatpump\n"
    assert _matches(PLUMBING, text) == []


def test_the_plumbing_check_sees_a_violation():
    """It finds each word as a name, in a comment and in a docstring,
    in any case, and passes the heater's heat pump."""
    text = (
        '"""Recirculation through the loop."""\n'
        "pump_runs = PumpRuns()\n"
        "for x in y:  # a loop\n"
        "class RecircParams: ...\n"
        "def f(): return 1  # the circulation PUMP\n"
        "# The heat pump, a heat-pump start, HEAT_PUMP, heat_pump mode.\n"
        "# Circulation, a gallon, a scoop: none of them is plumbing.\n"
    )
    assert [(n, w.lower()) for n, w in _matches(PLUMBING, text)] == [
        (1, "recirc"),
        (1, "loop"),
        (2, "pump"),
        (2, "pump"),
        (3, "loop"),
        (4, "recirc"),
        (5, "pump"),
    ]


def _loaded_after(statement: str) -> list[str]:
    """The modules a fresh interpreter holds after ``statement``."""
    script = (
        "import json, sys\n"
        f"{statement}\n"
        "print(json.dumps(sorted(sys.modules)))\n"
    )
    # The child sees this interpreter's sys.path, so it imports this
    # checkout rather than wherever an installed copy lives.
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
    out = subprocess.run(  # noqa: S603
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    loaded: list[str] = json.loads(out.stdout)
    return loaded


def test_importing_nwp500_does_not_load_the_simulator():
    loaded = _loaded_after("import nwp500")
    assert "nwp500" in loaded
    assert not [m for m in loaded if m.split(".")[:2] == ["nwp500", "sim"]]
