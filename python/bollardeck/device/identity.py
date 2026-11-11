# SPDX-License-Identifier: Apache-2.0
"""
bollardeck.device.identity: device serials and the maker registry.

Every device has a serial like `PB0007-UNOQ-2822080200`:

    PB{number:04d}-{maker}-{hardware_id}

`number` is the unit's number (0 until it is given one, shown as `PBOLL #????`), `maker` is a
maker code from the registry, and `hardware_id` ties the serial to the board it runs on. Virtual
devices carry `VPB...` serials.

    from bollardeck.device import identity

    identity.parse("PB0007-UNOQ-2822080200")
    # Serial(virtual=False, number=7, maker="UNOQ", hardware_id="2822080200")
    identity.format_serial(7, "2822080200", "UNOQ")        # "PB0007-UNOQ-2822080200"
    identity.validate_serial("PB0007-ACME-1234ABCD")       # ["maker code 'ACME' is reserved (...)"]
    identity.is_device_serial("PB0007-UNOQ-2822080200")    # True
    identity.label_for(7)                                  # "PBOLL #0007"

    me = identity.read_identity("/popbollard/data")        # this device's own identity file, or None
    me.serial, me.number, me.maker, me.label

**Two strictnesses, on purpose.** `parse` is as lenient as serials in the field need: any maker
text, virtual serials, old test serials. `validate_serial` is the strict check for a physical
device: a well-formed maker code that the registry lists as first-party or third-party, and a
hardware id of 1 to 32 letters and digits. They are the two patterns in the `device-identity`
schema (`#/$defs/serial` and `#/$defs/device_serial`).

**Maker codes** are 3 to 6 upper-case letters or digits, starting with a letter; a third party's
code is letters only. The registry (`popboll.makers/1`) ships inside this package:
`load_makers()` returns its rows, and `load_makers(path)` reads another copy, falling back to
the packaged one when that file is missing or does not validate. `validate_registry(document)`
gives the `makers` schema's verdict plus the one rule a schema cannot state, that no code is
listed twice.

**What is not here.** This module reads. It does not make up a serial, probe hardware for an id,
give a device its number, or write an identity file, and it never touches a secure element. Those
belong to the device's own firmware.

`read_identity` returns None when there is no file, and raises `IdentityError` when there is one
that does not fit the `device-identity` schema. The two are kept apart because a caller that
treats "unreadable" as "absent" would go on to give a device a second identity.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, NamedTuple, Optional, Tuple, Union

from .. import schema as _schema
from ._makers import REGISTRY_JSON

__all__ = ["Serial", "DeviceIdentity", "IdentityError", "parse", "parse_serial", "format_serial", "maker_code",
           "number_from_serial", "song_id_prefix", "label_for", "validate_serial", "is_device_serial",
           "is_maker_code", "validate_registry", "load_makers", "maker_entry", "is_registered_maker",
           "registry", "identity_path", "identity_problems", "load_identity_file", "read_identity",
           "known_serial", "IDENTITY_FILENAME", "SCHEMA_VERSION", "MAKERS_SCHEMA", "MAKER_KINDS",
           "ASSIGNED_KINDS", "UNPROVISIONED_LABEL", "ENV_SERIAL", "ENV_DATA_DIR"]

logger = logging.getLogger("bollardeck.identity")

IDENTITY_FILENAME = "device_identity.json"
SCHEMA_VERSION = 1
ENV_SERIAL = "POPBOLLARD_DEVICE_SERIAL"
ENV_DATA_DIR = "POPBOLLARD_DATA_DIR"
MAKERS_SCHEMA = "popboll.makers/1"
MAKER_KINDS = ("first-party", "third-party", "reserved")
ASSIGNED_KINDS = ("first-party", "third-party")
UNPROVISIONED_LABEL = "PBOLL #????"
MAX_NUMBER = 999999

MAKER_CODE_RE = re.compile(r"^[A-Z][A-Z0-9]{2,5}\Z")           # any code in a serial
THIRD_PARTY_CODE_RE = re.compile(r"^[A-Z]{3,6}\Z")             # a code the registry gives a third party
# PB0007-UNOQ-2822080200, VPB0007-WEB-pb-k3x9qa, VPB0007-CLOUD-LILDOCKER, PB0002-PEER-99887766
SERIAL_RE = re.compile(r"^(V?)PB(\d{4,6})-([A-Za-z0-9]+)-(.+)\Z", re.ASCII)
# A physical device's serial, strictly.
DEVICE_SERIAL_RE = re.compile(r"^PB(\d{4,6})-([A-Z][A-Z0-9]{2,5})-([A-Za-z0-9]{1,32})\Z", re.ASCII)


class IdentityError(ValueError):
    """An identity file that is there and cannot be used."""


class Serial(NamedTuple):
    """The parts of a serial. `maker` is upper-cased; it is not checked against the registry."""
    virtual: bool
    number: int
    maker: str
    hardware_id: str


@dataclass(frozen=True)
class DeviceIdentity:
    serial: str
    number: int
    label: str
    hardware_id: str
    source: str          # env | file | hardware:<where> | random

    @property
    def maker(self) -> str:
        """The serial's maker code ("" when the serial does not parse)."""
        return maker_code(self.serial) or ""

    def to_dict(self) -> dict:
        return dict(asdict(self), maker=self.maker)


# ── serials ──────────────────────────────────────────────────────────────────────────────

def parse(serial: Any) -> Optional[Serial]:
    """The parts of a PB... or VPB... serial, else None. Lenient: see the module docstring."""
    m = SERIAL_RE.match(str(serial or "").strip())
    if not m:
        return None
    return Serial(bool(m.group(1)), int(m.group(2)), m.group(3).upper(), m.group(4))


def parse_serial(serial: Any) -> Optional[Tuple[int, str]]:
    """(number, hardware_id) for a PB... / VPB... serial, else None."""
    parts = parse(serial)
    return (parts.number, parts.hardware_id) if parts else None


def maker_code(serial: Any) -> Optional[str]:
    """The maker code of a serial, upper-cased (`UNOQ` for `PB0007-UNOQ-...`), else None."""
    parts = parse(serial)
    return parts.maker if parts else None


def number_from_serial(serial: Any) -> Optional[int]:
    parts = parse(serial)
    return parts.number if parts else None


def song_id_prefix(serial: Any) -> str:
    """`pb0007` for `PB0007-...` (and `VPB0007-...`); `pb0000` when the serial has no number."""
    return "pb%04d" % (number_from_serial(serial) or 0)


def label_for(number: int) -> str:
    return "PBOLL #%04d" % int(number) if int(number) > 0 else UNPROVISIONED_LABEL


def is_maker_code(code: Any) -> bool:
    """Is this text shaped like a maker code? Says nothing about the registry."""
    return isinstance(code, str) and bool(MAKER_CODE_RE.match(code))


def format_serial(number: int, hardware_id: str, maker: str, *, virtual: bool = False) -> str:
    """`PB{number:04d}-{maker}-{hardware_id}` (`VPB...` when virtual). Raises ValueError for a
    number outside 0 to 999999, a maker that is not shaped like a maker code, or an empty hardware
    id: the result always parses. This writes a serial down; it does not assign one."""
    if isinstance(number, bool) or not isinstance(number, int) or not 0 <= number <= MAX_NUMBER:
        raise ValueError("a serial's number runs from 0 to %d, not %r" % (MAX_NUMBER, number))
    code = str(maker or "").strip().upper()
    if not MAKER_CODE_RE.match(code):
        raise ValueError("bad maker code %r (3 to 6 upper-case letters or digits, starting with a letter)" % code)
    hw = str(hardware_id or "")
    if not hw or hw != hw.strip() or "\n" in hw:
        raise ValueError("a serial needs a hardware id, not %r" % (hardware_id,))
    return "%sPB%04d-%s-%s" % ("V" if virtual else "", number, code, hw)


# ── the maker registry ───────────────────────────────────────────────────────────────────

_PACKAGED: Optional[Dict[str, Any]] = None


def registry() -> Dict[str, Any]:
    """The maker registry document this package ships (a fresh copy each call)."""
    global _PACKAGED
    if _PACKAGED is None:
        _PACKAGED = json.loads(REGISTRY_JSON)
    return json.loads(json.dumps(_PACKAGED))


def validate_registry(data: Any) -> List[str]:
    """Every problem with a maker registry document ([] when it is fine): what the `makers` schema
    refuses, and any code listed twice."""
    errors = ["%s: %s" % (p.pointer or "(document)", p.message) for p in _schema.validate("makers", data)]
    if isinstance(data, dict) and isinstance(data.get("makers"), list):
        seen = set()
        for i, row in enumerate(data["makers"]):
            code = row.get("code") if isinstance(row, dict) else None
            if isinstance(code, str):
                if code in seen:
                    errors.append("/makers/%d: %r is listed twice" % (i, code))
                seen.add(code)
    return errors


def load_makers(path: Union[str, Path, None] = None) -> List[dict]:
    """The registry's rows: the packaged registry, or the one in `path`. When `path` is missing or
    does not validate, the packaged rows (and a logged warning), so a device never fails for want
    of the file."""
    if path is not None:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("maker registry %s cannot be read (%s); using the packaged one", path, type(exc).__name__)
        else:
            found = validate_registry(data)
            if not found:
                return [dict(r) for r in data["makers"]]
            logger.warning("maker registry %s is not valid (%s); using the packaged one", path, found[0])
    return [dict(r) for r in registry()["makers"]]


def _rows(makers: Any) -> List[dict]:
    """Rows from whatever a caller passed as `makers`: None (packaged), a path, or rows."""
    if makers is None or isinstance(makers, (str, Path)):
        return load_makers(makers)
    return [dict(r) for r in makers]


def maker_entry(code: Any, makers: Any = None) -> Optional[dict]:
    """The registry row for a maker code, else None. `makers` is None for the packaged registry, a
    path to another copy, or a list of rows."""
    want = str(code or "").strip().upper()
    for row in _rows(makers):
        if row.get("code") == want:
            return row
    return None


def is_registered_maker(code: Any, makers: Any = None) -> bool:
    """True for a first-party or third-party code in the registry. Reserved codes (the simulator,
    the virtual and test codes, the documentation examples) and unknown codes are not registered."""
    row = maker_entry(code, makers)
    return bool(row) and row["kind"] in ASSIGNED_KINDS


def validate_serial(serial: Any, makers: Any = None) -> List[str]:
    """Every reason `serial` is not a physical device's serial with a registered maker ([] = fine)."""
    text = str(serial or "").strip()
    if text.startswith("VPB"):
        return ["%r is a virtual serial, not a device's" % text]
    m = DEVICE_SERIAL_RE.match(text)
    if not m:
        if SERIAL_RE.match(text):
            return ["%r: the maker code must be 3 to 6 upper-case letters or digits starting with a "
                    "letter, and the hardware id 1 to 32 letters or digits" % text]
        return ["%r is not PB####-<MAKER>-<hardware id>" % text]
    code = m.group(2)
    row = maker_entry(code, makers)
    if row is None:
        return ["maker code %r is not in the registry" % code]
    if row["kind"] not in ASSIGNED_KINDS:
        return ["maker code %r is reserved (%s)" % (code, row.get("notes") or row["kind"])]
    return []


def is_device_serial(serial: Any, makers: Any = None) -> bool:
    return not validate_serial(serial, makers)


# ── a device's own identity file ─────────────────────────────────────────────────────────

def identity_path(where: Union[str, Path, None] = None, env: Optional[Mapping[str, str]] = None) -> Optional[Path]:
    """The identity file for `where`: the file itself when `where` names a .json file, else
    `<where>/device_identity.json`. With no `where`, the data directory is $POPBOLLARD_DATA_DIR;
    None when that is not set either."""
    if where is None:
        raw = ((os.environ if env is None else env).get(ENV_DATA_DIR) or "").strip()
        if not raw:
            return None
        where = raw
    p = Path(where)
    return p if p.suffix == ".json" else p / IDENTITY_FILENAME


def identity_problems(document: Any) -> List[str]:
    """Every reason a parsed identity file cannot be used ([] = fine): the `device-identity`
    schema's verdict."""
    return ["%s: %s" % (p.pointer or "(document)", p.message) for p in _schema.validate("device-identity", document)]


def load_identity_file(where: Union[str, Path, None] = None, env: Optional[Mapping[str, str]] = None) -> Optional[dict]:
    """The identity file as a dict; None when there is no file. Raises `IdentityError` for a file
    that is not JSON or does not fit the `device-identity` schema."""
    path = identity_path(where, env)
    if path is None:
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as exc:
        raise IdentityError("%s cannot be read (%s)" % (path, type(exc).__name__)) from exc
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise IdentityError("%s is not JSON" % path) from exc
    found = identity_problems(data)
    if found:
        raise IdentityError("%s is not a device identity: %s" % (path, "; ".join(found)))
    return data


def read_identity(where: Union[str, Path, None] = None, env: Optional[Mapping[str, str]] = None) -> Optional[DeviceIdentity]:
    """This device's identity as its file states it; None when there is no file. The number is
    the file's `number`, else the serial's; the hardware id is the file's, else the serial's.
    `source` is "file". Never probes hardware and never writes."""
    saved = load_identity_file(where, env)
    if saved is None:
        return None
    serial = saved["serial"].strip()
    parts = parse(serial)
    number = saved.get("number")
    if number is None:
        number = parts.number if parts else 0
    hw = str(saved.get("hardware_id") or (parts.hardware_id if parts else serial))
    return DeviceIdentity(serial, int(number), label_for(int(number)), hw, "file")


def known_serial(where: Union[str, Path, None] = None, env: Optional[Mapping[str, str]] = None) -> str:
    """This device's serial when one is already settled: $POPBOLLARD_DEVICE_SERIAL, else the
    identity file's, else "". Never probes hardware and never writes."""
    forced = ((os.environ if env is None else env).get(ENV_SERIAL) or "").strip()
    if forced:
        return forced
    saved = load_identity_file(where, env)
    return saved["serial"].strip() if saved else ""
