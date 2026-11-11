# SPDX-License-Identifier: Apache-2.0
"""bollardeck.routines.errors: the exceptions of the routine API."""


class RoutineError(Exception):
    """A routine broke a rule (bad manifest, bad result, limit breach, guarded operation)."""


class RoutineSetupError(RuntimeError):
    """The host program used the routine API wrongly (for example, no factory was given). Unlike
    a `RoutineError` this is never recorded and skipped: it is the host's bug and it is raised."""
