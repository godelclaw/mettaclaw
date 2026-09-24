"""The prompt-layout invariant that makes provider prefix caching work.

Two requests from consecutive turns must agree on everything before the last
cache boundary, and nothing that changes every turn may appear there.  The
stable head (prompt, skills, output format, context order) comes before the
first boundary.  Used by prompt_cache_layout_probe.metta on the real renderer.
"""

BOUNDARY = "_cache_boundary_"
LAYOUT_BOUNDARIES = 3
HEAD = ("PROMPT:", "OUTPUT_FORMAT:", "CONTEXT_ORDER:")
SKILLS = ("SKILLS:", "ADVERTISED_CAPABILITIES:")
PER_TURN = (
    "LOOPS_LEFT:", "SLEEP_INTERVAL_SECONDS:", "ACTIVE_MODE:",
    "ACTIVE_MODEL:", "ATTENTION_DAG:", "LAST_SKILL_USE_RESULTS:", "TIME:",
    "NEW_ACTIVITY:", "CONTEXT_CERTIFICATE",
)


def violations(first, second):
    """Everything wrong with the pair, as short strings; empty when sound."""
    first, second = str(first), str(second)
    problems = []
    for name, text in (("first", first), ("second", second)):
        if text.count(BOUNDARY) != LAYOUT_BOUNDARIES:
            problems.append("%s has %d boundaries" % (
                name, text.count(BOUNDARY)))
    if problems:
        return problems
    stable = first[:first.rindex(BOUNDARY)]
    if stable != second[:second.rindex(BOUNDARY)]:
        problems.append("the prefix before the last boundary differs")
    head = first[:first.index(BOUNDARY)]
    problems += ["head lacks " + mark for mark in HEAD if mark not in head]
    if not any(mark in head for mark in SKILLS):
        problems.append("head lacks the skills")
    problems += ["per-turn " + mark + " before the last boundary"
                 for mark in PER_TURN if mark in stable]
    return problems


def ok(first, second):
    problems = violations(first, second)
    if problems:
        print("PROMPT_LAYOUT_VIOLATIONS", problems)
    return 0 if problems else 1
