#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
pin_vectors.py: fill in the expected values of the behaviour vectors.

    conformance/cue-render/*.json   cue list + time -> what each button shows
    conformance/matrix/*.json       inputs -> the frame the matrix engine makes

    tools/pin_vectors.py           write the cue values and the matrix values
    tools/pin_vectors.py --check   write nothing; exit 1 when a value differs

The values come from this repository's own Python: the cue values from bollardeck.device.cues and
the matrix values from bollardeck.matrix. The browser binding is then held to both. Each vector
file names, in "pinned_to", the module its values come from.

The inputs are authored by hand in the vector files; this tool only writes the members "frame",
"value", "buttons", "constants" and "pinned_to". Nobody needs this tool to run the vectors.
Standard library only.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
MATRIX_DIR = ROOT / "conformance" / "matrix"
CUE_DIR = ROOT / "conformance" / "cue-render"
ONE_PER_LINE = ("fixtures", "vectors")


def dumps(doc):
    """The vector file's text: one line per top-level member, per fixture and per vector."""
    def line(value):
        return json.dumps(value, ensure_ascii=True, separators=(", ", ": "))
    out = []
    for key, value in doc.items():
        if key in ONE_PER_LINE and isinstance(value, dict):
            inner = ",\n".join("  %s: %s" % (json.dumps(k), line(v)) for k, v in value.items())
            out.append(' %s: {\n%s\n }' % (json.dumps(key), inner))
        elif key in ONE_PER_LINE:
            out.append(' %s: [\n%s\n ]' % (json.dumps(key), ",\n".join("  " + line(v) for v in value)))
        else:
            out.append(" %s: %s" % (json.dumps(key), line(value)))
    return "{\n" + ",\n".join(out) + "\n}\n"


# ── the matrix ───────────────────────────────────────────────────────────────────────────

def resolve(value, fixtures):
    """An argument, with {"$fixture": name} replaced by that fixture."""
    if isinstance(value, dict) and set(value) == {"$fixture"}:
        return fixtures[value["$fixture"]]
    return value


def matrix_result(lm, call, args):
    """("frame", hex) or ("value", anything) for one vector, from the engine module `lm`."""
    g = args.get
    frame = lambda h: lm.MatrixFrame.from_bytes(bytes.fromhex(h))      # noqa: E731
    if call == "film":
        return "frame", lm.film_frame(g("song"), g("t_ms"), bool(g("calm", False))).hex()
    if call == "playback":
        return "frame", lm.playback_frame(g("song"), g("pos_s"), bool(g("calm", False))).hex()
    if call == "idle":
        return "frame", lm.idle_frame(g("t_ms"), bool(g("calm", False)), g("temperament")).hex()
    if call == "corpus":
        return "frame", lm.corpus_frame(g("t_ms"), g("level", 0), g("bands"), bool(g("calm", False))).hex()
    if call == "glyph":
        return "frame", lm.glyph_frame(g("name"), g("t_ms"), bool(g("calm", False))).hex()
    if call == "dj":
        return "frame", lm.dj_frame(g("seg"), g("pos_s"), g("t_ms", 0), bool(g("calm", False))).hex()
    if call == "text":
        return "frame", lm.text_frame(g("text"), g("t_ms"), bool(g("loop", True)), g("priority", "pairing"),
                                      g("ttl_ms"), bool(g("calm", False))).hex()
    if call == "premiere":
        return "frame", lm.premiere_frame(g("number"), g("t_ms"), bool(g("opened", False)), bool(g("calm", False)),
                                          g("tier", "")).hex()
    if call == "tone":
        return "frame", lm.tone_frame(frame(g("frame")), g("tone")).hex()
    if call == "dj_beat":
        return "value", lm.dj_beat(g("seg"), g("pos_s"))
    if call == "dj_crossfader":
        return "value", lm.dj_crossfader(g("seg"), g("pos_s"))
    if call == "dj_camelot":
        return "value", list(lm.dj_camelot(g("value")))
    if call == "text_pass_ms":
        return "value", lm.text_pass_ms(g("text"))
    if call == "str_seed":
        return "value", lm.str_seed(g("text"))
    if call == "ascii":
        return "value", lm.to_ascii(frame(g("frame")))
    raise SystemExit("pin_vectors: no matrix call named %r" % call)


def sdk_matrix():
    sys.path.insert(0, str(ROOT / "python"))
    from bollardeck import matrix
    return matrix


def pin_matrix(doc):
    """Write the vectors' values from bollardeck.matrix."""
    lm = sdk_matrix()
    fixtures = doc.get("fixtures", {})
    for v in doc["vectors"]:
        args = {k: resolve(a, fixtures) for k, a in v["args"].items()}
        v.pop("frame", None)
        v.pop("value", None)
        key, result = matrix_result(lm, v["call"], args)
        v[key] = result
    doc["pinned_to"] = {"python": "bollardeck.matrix"}
    return doc


# ── the cues ─────────────────────────────────────────────────────────────────────────────

def pin_cues(doc):
    sys.path.insert(0, str(ROOT / "python"))
    from bollardeck import constants
    from bollardeck.device import cues
    doc["constants"] = {name: getattr(constants, name)
                        for name in ("PULSE_PERIOD_MS", "CHASE_PERIOD_MS", "PULSE_FLOOR", "CHASE_TAIL", "CHASE_STEPS")}
    for v in doc["vectors"]:
        v["buttons"] = cues.at(v["cues"], v["t_ms"], calm=bool(v.get("calm", False)))
    doc["pinned_to"] = {"python": "bollardeck.device.cues"}
    return doc


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    check = args == ["--check"]
    if args and not check:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    jobs = [(p, pin_cues) for p in sorted(CUE_DIR.glob("*.json"))]
    jobs += [(p, pin_matrix) for p in sorted(MATRIX_DIR.glob("*.json"))]
    stale, pinned = [], []
    for path, pin in jobs:
        before = path.read_text(encoding="utf-8")
        after = dumps(pin(json.loads(before)))
        if after != before:
            stale.append(str(path.relative_to(ROOT)))
            pinned.append((path, after))
    if check:
        for rel in stale:
            print("pin_vectors: %s is not what the engine makes; run tools/pin_vectors.py" % rel, file=sys.stderr)
        return 1 if stale else 0
    for path, after in pinned:
        path.write_text(after, encoding="utf-8")
        print("pin_vectors: wrote %s" % path.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
