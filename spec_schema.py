"""Server-side validation for a methodology spec.

The browser validates too, but this is the authoritative check — never trust the
client. Mirrors the locked required-fields rule:
  - a methodology name
  - trader.style_summary
  - at least one setup with both a trigger and an invalidation
  - at least one hard filter
Everything else is optional and only adds richness.
"""


def _nonempty(v):
    return isinstance(v, str) and v.strip() != ""


def validate_spec(name, spec):
    """Return a list of human-readable error strings (empty == valid)."""
    errors = []
    if not _nonempty(name):
        errors.append("Give your methodology a name.")

    if not isinstance(spec, dict):
        return ["Malformed spec."]

    trader = spec.get("trader") or {}
    if not _nonempty(trader.get("style_summary")):
        errors.append("Write a one-line style summary (section 1).")

    setups = spec.get("setups") or []
    valid_setups = [
        s for s in setups
        if isinstance(s, dict) and _nonempty(s.get("trigger")) and _nonempty(s.get("invalidation"))
    ]
    if not valid_setups:
        errors.append("Add at least one setup with both a trigger and an invalidation (section 4).")
    if len(setups) > 5:
        errors.append("Maximum of 5 setups.")

    conviction = spec.get("conviction_rules") or {}
    hard_filters = [f for f in (conviction.get("hard_filters") or []) if _nonempty(f)]
    if not hard_filters:
        errors.append("Add at least one hard filter — an absolute no-go condition (section 5).")

    return errors
