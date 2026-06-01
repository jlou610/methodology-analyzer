"""The analyzer: runs a user's per-session observation against THEIR methodology
spec and returns a structured read graded in their own vocabulary.

Prompt caching is implemented here (see run_analysis): the system prompt — the
generic analyzer instructions plus the user's serialized spec — is stable across
that user's repeated analyses, so it's sent as a cache_control ephemeral block.
The volatile per-session observation goes in the user message, outside the cached
prefix. Verify via usage.cache_creation_input_tokens (first call) /
cache_read_input_tokens (subsequent calls within the 5-minute TTL).
"""
import json
import re

import anthropic

# Sonnet 4.6: cheaper than Opus and has a 1024-token cache minimum (vs 4096),
# so caching engages on a modest spec. Flip to "claude-opus-4-8" to upgrade.
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 1500

SECTIONS = ["CONTEXT_READ", "SETUPS_IN_PLAY", "TOP_READ", "RED_FLAGS", "WHAT_WOULD_CHANGE_THIS"]

ANALYZER_PREAMBLE = """You are a disciplined trading-analysis assistant. You work for ONE trader and \
reason STRICTLY within the methodology spec provided below — their markets, their setups, their \
rules, their vocabulary. You are not a general market commentator.

Hard rules:
- Reason ONLY in terms of the setups, context inputs, and rules defined in the methodology. NEVER \
invent a setup, indicator, or level that is not in their playbook.
- Reference the specific levels/observations the trader gave you. Never fabricate prices or data.
- If the situation matches none of their setups, say so plainly in TOP_READ rather than forcing one.
- Be concise and direct. No hedging, no generic trading advice, no disclaimers.
- Use the trader's own term for supporting conditions (given as the confluence label below).

You MUST grade conviction using ONLY the trader's grading scale (defined below). Do not substitute \
a generic A/B/C scale unless those are literally their tiers.

Respond using EXACTLY these five section headers, each on its own line, in this order, with nothing \
before the first header:

CONTEXT_READ:
<Read the current situation through the trader's context inputs — trend, levels, and whatever else \
their methodology tracks. 2-4 sentences.>

SETUPS_IN_PLAY:
<For each of the trader's setups that could be in play now: name it, state why it matches (or which \
confluence is present/absent), give its conviction grade using the trader's scale, and the \
invalidation level. If none are in play, say so.>

TOP_READ:
<The single highest-conviction read right now, with the specific level. One short paragraph.>

RED_FLAGS:
<Any of the trader's red flags or hard filters that are tripped right now. If none, say "None tripped."

WHAT_WOULD_CHANGE_THIS:
<The specific observation that would flip or invalidate the read above.>
"""


def _g(d, *keys, default=""):
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k, default)
    return cur if cur is not None else default


def grading_instruction(spec):
    gs = _g(spec, "conviction_rules", "grading_scale", default={}) or {}
    if gs.get("type") == "numeric":
        rng = gs.get("range") or "1-10"
        instr = f"GRADING SCALE: numeric, range {rng} (higher = stronger conviction). " \
                f"Grade each setup as a number on this scale."
    else:
        tiers = [t for t in (gs.get("tiers") or []) if t]
        if not tiers:
            tiers = ["A", "B", "C"]
        instr = "GRADING SCALE: named tiers, best to worst: " + ", ".join(tiers) + ". " \
                f"Grade each setup using ONLY these labels — do not use any other grading words."
    notes = gs.get("notes")
    if notes:
        instr += f" Notes on grading: {notes}"
    return instr


def serialize_spec(spec):
    """Deterministic, human-readable rendering of the spec for the system prompt.
    Field order is fixed so the cached prefix is byte-stable across calls."""
    t = spec.get("trader") or {}
    conf_label = _g(spec, "terminology", "confluence_label", default="Confluence") or "Confluence"
    lines = ["=== METHODOLOGY SPEC ==="]
    if t.get("name"):
        lines.append(f"Trader: {t['name']}")
    lines.append(f"Style: {t.get('style_summary', '')}")
    if t.get("edge_thesis"):
        lines.append(f"Edge thesis (why this works): {t['edge_thesis']}")
    if t.get("markets"):
        lines.append(f"Markets: {', '.join(t['markets'])}")
    if t.get("instruments"):
        lines.append(f"Instruments: {', '.join(t['instruments'])}")
    if t.get("holding_style"):
        lines.append(f"Holding style: {t['holding_style']}")
    tf = t.get("timeframes") or {}
    if tf.get("context") or tf.get("trigger"):
        lines.append(f"Timeframes — context: {', '.join(tf.get('context', []))}; "
                     f"trigger: {', '.join(tf.get('trigger', []))}")
    if t.get("workflow"):
        lines.append(f"Workflow: {t['workflow']}")

    ci = spec.get("context_inputs") or []
    if ci:
        lines.append("\nCONTEXT INPUTS (what the trader reads before deciding):")
        for c in ci:
            lines.append(f"- {c.get('name', '')}: {c.get('what_it_tells_me', '')}")

    lines.append(f"\nSETUPS (the playbook). The trader calls supporting conditions \"{conf_label}\":")
    for i, s in enumerate(spec.get("setups") or [], 1):
        lines.append(f"\nSetup {i}: {s.get('name', '')} [{s.get('direction', '')}]")
        if s.get("thesis"):
            lines.append(f"  Thesis: {s['thesis']}")
        if s.get("trigger"):
            lines.append(f"  Trigger: {s['trigger']}")
        if s.get("confluence"):
            lines.append(f"  {conf_label}: " + "; ".join(s["confluence"]))
        if s.get("invalidation"):
            lines.append(f"  Invalidation: {s['invalidation']}")
        if s.get("red_flags"):
            lines.append("  Red flags: " + "; ".join(s["red_flags"]))
        if s.get("management"):
            lines.append(f"  Management: {s['management']}")

    cr = spec.get("conviction_rules") or {}
    lines.append("\nCONVICTION RULES:")
    if cr.get("high_conviction"):
        lines.append(f"- High conviction: {cr['high_conviction']}")
    if cr.get("low_or_skip"):
        lines.append(f"- Low conviction / skip: {cr['low_or_skip']}")
    if cr.get("hard_filters"):
        lines.append("- Hard filters (absolute no-go): " + "; ".join(cr["hard_filters"]))

    risk = spec.get("risk") or {}
    if any(risk.get(k) for k in ("per_trade", "max_concurrent", "notes")):
        lines.append("\nRISK:")
        if risk.get("per_trade"):
            lines.append(f"- Per trade: {risk['per_trade']}")
        if risk.get("max_concurrent"):
            lines.append(f"- Max concurrent: {risk['max_concurrent']}")
        if risk.get("notes"):
            lines.append(f"- Notes: {risk['notes']}")

    return "\n".join(lines)


def build_system_text(spec):
    return ANALYZER_PREAMBLE + "\n\n" + grading_instruction(spec) + "\n\n" + serialize_spec(spec)


def build_user_text(analysis_input):
    title = (analysis_input.get("title") or "").strip()
    obs = (analysis_input.get("observations") or "").strip()
    head = f"What I'm looking at: {title}\n\n" if title else ""
    return (head + f"Current situation / observations:\n{obs}\n\n"
            "Analyze this against my methodology and respond in the required five-section format.")


def parse_sections(text):
    """Split the model output into the five named sections. Tolerates optional
    markdown (#, *, leading whitespace) around the headers."""
    positions = []
    for key in SECTIONS:
        m = re.search(rf"(?im)^[ \t#*>]*{re.escape(key)}[ \t]*:?\s*$", text) \
            or re.search(rf"(?im)^[ \t#*>]*{re.escape(key)}[ \t]*:", text)
        if m:
            positions.append((m.start(), m.end(), key))
    positions.sort()
    out = {k: "" for k in SECTIONS}
    for idx, (start, end, key) in enumerate(positions):
        body_end = positions[idx + 1][0] if idx + 1 < len(positions) else len(text)
        out[key] = text[end:body_end].strip()
    return out


def run_analysis(spec, analysis_input):
    """Call Claude with the user's methodology as a cached system prompt.
    Returns dict: text, sections, usage. Raises anthropic.* on API failure."""
    system_text = build_system_text(spec)
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    resp = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=[
            {
                "type": "text",
                "text": system_text,
                "cache_control": {"type": "ephemeral"},  # <-- prompt caching enabled here
            }
        ],
        messages=[{"role": "user", "content": build_user_text(analysis_input)}],
    )
    text = next((b.text for b in resp.content if b.type == "text"), "")
    u = resp.usage
    return {
        "text": text,
        "sections": parse_sections(text),
        "usage": {
            "input_tokens": u.input_tokens,
            "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
            "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
            "output_tokens": u.output_tokens,
        },
        "model": MODEL,
    }
