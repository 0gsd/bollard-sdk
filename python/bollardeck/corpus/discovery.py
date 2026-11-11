# SPDX-License-Identifier: Apache-2.0
"""
bollardeck.corpus.discovery: find corpora in local folders and on a hub, and pick a set.

    found = discover(roots=["/media/sd/corpora"], hub=hub)
    chosen = found.corpora.select(["9001-PLACEHOLDERS"])        # MissingCorpora if it is not there

Rules:

  * A local root is a corpus folder (it holds corpus.json) or a folder of corpus folders.
    Children whose names start with "." or "_" are work folders and are skipped. A folder
    without corpus.json is not a corpus.
  * The first corpus seen for an id wins, and local beats the hub, unless prefer_remote.
  * A manifest the SDK will not read is not dropped silently: it is listed in `refused`.
  * With an identity, corpora that identity may not see are left out and listed in `refused`.
  * Selecting ids that are not there is an error. A caller who wants another behaviour says so:
    if_missing="skip" (take what is there) or if_missing="all" (today's Pop Boll fallback: when
    none of the ids is there, take every corpus). Either way the result records what happened.
"""

from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from .gate import SEE, Identity, Verdict
from .model import MANIFEST_NAME, MORPUS_DIRNAME, Corpus, ManifestRefused

Refusal = Tuple[str, str, Tuple[str, ...]]      # (where or id, reason, problems)


class MissingCorpora(LookupError):
    """Ids were asked for that are not in the set."""

    def __init__(self, missing: Sequence[str], have: Sequence[str]):
        self.missing = list(missing)
        self.have = list(have)
        super().__init__("no such corpus: %s (have: %s)" % (", ".join(self.missing), ", ".join(self.have) or "none"))


class CorpusSet:
    """Corpora, in (number, id) order. `missing` and `substituted` say what select() had to do."""

    def __init__(self, corpora: Iterable[Corpus], missing: Sequence[str] = (), substituted: bool = False):
        self._corpora = sorted(corpora, key=lambda c: (c.number, c.id))
        self.missing = list(missing)
        self.substituted = bool(substituted)

    def __iter__(self) -> Iterator[Corpus]:
        return iter(self._corpora)

    def __len__(self) -> int:
        return len(self._corpora)

    def __bool__(self) -> bool:
        return bool(self._corpora)

    @property
    def ids(self) -> List[str]:
        return [c.id for c in self._corpora]

    def get(self, corpus_id: str) -> Optional[Corpus]:
        for c in self._corpora:
            if c.id == corpus_id:
                return c
        return None

    def select(self, corpus_ids: Optional[Iterable[str]], if_missing: str = "error") -> "CorpusSet":
        """The corpora with these ids (all of them when corpus_ids is None).

        if_missing="error"  raise MissingCorpora naming every id that is not here (the default)
        if_missing="skip"   return the ones that are here; `missing` lists the rest
        if_missing="all"    when NONE of the ids is here, return every corpus with
                            substituted=True; otherwise as "skip"
        """
        if if_missing not in ("error", "skip", "all"):
            raise ValueError('if_missing is "error", "skip" or "all", not %r' % (if_missing,))
        if corpus_ids is None:
            return CorpusSet(self._corpora)
        if isinstance(corpus_ids, str):
            corpus_ids = [corpus_ids]
        wanted = list(dict.fromkeys(corpus_ids))
        missing = [i for i in wanted if self.get(i) is None]
        if missing and if_missing == "error":
            raise MissingCorpora(missing, self.ids)
        chosen = [c for c in self._corpora if c.id in wanted]
        if not chosen and wanted and if_missing == "all":
            return CorpusSet(self._corpora, missing, substituted=True)
        return CorpusSet(chosen, missing)

    def allowed(self, capability: str, identity: Optional[Identity] = None,
                now: Any = None) -> Tuple[List[Tuple[Corpus, Verdict]], List[Tuple[Corpus, Verdict]]]:
        """Ask the gate about every corpus: ([(corpus, verdict) allowed], [(corpus, verdict) refused])."""
        yes, no = [], []
        for c in self._corpora:
            v = c.may(capability, identity, now)
            (yes if v else no).append((c, v))
        return yes, no

    def notices(self) -> List[Dict[str, Any]]:
        return [c.notices() for c in self._corpora]


class Discovery:
    """What discover() found: `corpora` (a CorpusSet) and `refused` (what was left out, and why)."""

    def __init__(self, corpora: CorpusSet, refused: List[Refusal]):
        self.corpora = corpora
        self.refused = refused

    def __iter__(self) -> Iterator[Corpus]:
        return iter(self.corpora)


def _local_candidates(root: Path) -> List[Path]:
    if root.name == MORPUS_DIRNAME and (root.parent / MANIFEST_NAME).is_file():
        return [root.parent]
    if (root / MANIFEST_NAME).is_file():
        return [root]
    try:
        return [p for p in sorted(root.iterdir())
                if p.is_dir() and not p.name.startswith((".", "_")) and (p / MANIFEST_NAME).is_file()]
    except OSError:
        return []


def discover(roots: Optional[Sequence[Any]] = None, hub=None, identity: Optional[Identity] = None,
             prefer_remote: bool = False, now: Any = None) -> Discovery:
    """Find corpora under `roots` and on `hub` (a HubClient). Never raises for a root that is
    missing or a hub that is down: local corpora stay, cached hub corpora stay."""
    by_id: Dict[str, Corpus] = {}
    refused: List[Refusal] = []
    seen_paths = set()
    for root in roots or []:
        root = Path(root)
        if not root.is_dir():
            continue
        for path in _local_candidates(root):
            try:
                key = str(path.resolve())
            except OSError:
                key = str(path)
            if key in seen_paths:
                continue
            seen_paths.add(key)
            try:
                c = Corpus.load(path)
            except ManifestRefused as exc:
                refused.append((str(path), exc.reason, exc.problems))
                continue
            by_id.setdefault(c.id, c)
    if hub is not None:
        remote, hub_refused = hub.corpora()
        refused.extend(hub_refused)
        for c in remote:
            if c.id not in by_id or prefer_remote:
                by_id[c.id] = c
    kept = []
    for c in by_id.values():
        if identity is not None:
            v = c.may(SEE, identity, now)
            if not v:
                refused.append((c.id, v.reason, (v.detail,)))
                continue
        kept.append(c)
    return Discovery(CorpusSet(kept), refused)
