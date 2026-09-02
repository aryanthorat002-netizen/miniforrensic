"""
Log Query DSL — a tiny domain-specific language + interpreter for
querying log files in plain syntax.

Supported query shapes:
    show all failed logins
    show all successful logins
    show all logins after 2am
    show all logins before 6am
    show all logins between 2am and 5am
    show all failed logins after 2am
    show all logins from user jdoe
    show all failed logins from ip 10.0.0.5
    show all logins not from user jdoe
    show all logins excluding ip 10.0.0.5
    show all failed logins or file_delete events        (OR across branches)

HOW IT WORKS:
  1. SPLIT: top-level "or" splits the query into independent branches.
  2. PARSE (per branch): regex pulls out status, event type, time bound
     (single-sided or range), field filter, and negation.
  3. COMPILE: each recognized piece becomes a small filter function.
  4. EXECUTE: filters within a branch combine with AND; branches
     combine with OR (set union) over the log rows.
"""

import csv
import re
from datetime import datetime


# ---------------------------------------------------------------------
# 1. LOAD LOG DATA
# ---------------------------------------------------------------------

def load_logs(path):
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    for i, row in enumerate(rows):
        row["_dt"] = datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S")
        row["_id"] = i  # stable id, used to dedupe OR results
    return rows


# ---------------------------------------------------------------------
# 2. PARSER
# ---------------------------------------------------------------------

def parse_time_expr(hour_str, ampm):
    hour = int(hour_str)
    ampm = ampm.lower()
    if ampm == "am":
        hour = 0 if hour == 12 else hour
    else:
        hour = 12 if hour == 12 else hour + 12
    return hour


def parse_single_branch(q):
    """Parse one AND-only clause (no 'or' inside it)."""
    filters = []
    description = []

    # --- negation marker: "not from user X" / "excluding ip X" ---
    neg_field_match = re.search(
        r"\b(?:not|excluding)\s+from\s+(user|ip)\s+([\w\.]+)", q
    )
    # also support "not from user X" written as "excluding user X" (no "from")
    if not neg_field_match:
        neg_field_match = re.search(
            r"\b(?:not|excluding)\s+(user|ip)\s+([\w\.]+)", q
        )

    # --- status: failed / successful / success ---
    status_match = re.search(r"\b(failed|successful|success)\b", q)
    if status_match:
        raw = status_match.group(1)
        status_value = "success" if raw in ("successful", "success") else "failed"
        filters.append(lambda row, v=status_value: row["status"] == v)
        description.append(f"status == {status_value}")

    # --- event type ---
    event_match = re.search(r"\b(logins?|file_access|file_delete)\b", q)
    if event_match:
        raw = event_match.group(1)
        event_value = "login" if raw.startswith("login") else raw
        filters.append(lambda row, v=event_value: row["event"] == v)
        description.append(f"event == {event_value}")

    # --- time range: "between 2am and 5am" (checked BEFORE single-sided) ---
    range_match = re.search(
        r"\bbetween\s+(\d{1,2})\s*(am|pm)\s+and\s+(\d{1,2})\s*(am|pm)\b", q
    )
    if range_match:
        h1_str, ampm1, h2_str, ampm2 = range_match.groups()
        h1 = parse_time_expr(h1_str, ampm1)
        h2 = parse_time_expr(h2_str, ampm2)
        filters.append(lambda row, a=h1, b=h2: a <= row["_dt"].hour < b)
        description.append(f"{h1} <= hour < {h2}")
    else:
        # --- single-sided time bound: "after 2am" / "before 6pm" ---
        time_match = re.search(r"\b(after|before)\s+(\d{1,2})\s*(am|pm)\b", q)
        if time_match:
            direction, hour_str, ampm = time_match.groups()
            hour = parse_time_expr(hour_str, ampm)
            if direction == "after":
                filters.append(lambda row, h=hour: row["_dt"].hour >= h)
                description.append(f"hour >= {hour}")
            else:
                filters.append(lambda row, h=hour: row["_dt"].hour < h)
                description.append(f"hour < {hour}")

    # --- field filter: "from user X" / "from ip X" (positive case) ---
    # skip if this exact span was already claimed by negation
    field_match = re.search(r"(?<!not )(?<!excluding )\bfrom\s+(user|ip)\s+([\w\.]+)", q)
    if field_match and not neg_field_match:
        field, value = field_match.groups()
        filters.append(lambda row, f=field, v=value: row[f] == v)
        description.append(f"{field} == {value}")

    # --- negated field filter ---
    if neg_field_match:
        field, value = neg_field_match.groups()
        filters.append(lambda row, f=field, v=value: row[f] != v)
        description.append(f"{field} != {value}")

    return filters, description


def parse_query(query):
    """
    Split on top-level 'or' into branches, parse each branch independently.
    Returns a list of (filters, description) tuples — one per OR branch.
    """
    q = query.lower().strip()
    branch_strings = re.split(r"\s+or\s+", q)
    branches = [parse_single_branch(b) for b in branch_strings]
    return branches


# ---------------------------------------------------------------------
# 3. INTERPRETER / EXECUTION ENGINE
# ---------------------------------------------------------------------

def run_query(logs, query):
    branches = parse_query(query)
    seen_ids = set()
    results = []
    branch_descriptions = []

    for filters, description in branches:
        branch_descriptions.append(description)
        if not filters:
            continue
        for row in logs:
            if row["_id"] in seen_ids:
                continue
            if all(f(row) for f in filters):
                results.append(row)
                seen_ids.add(row["_id"])

    # keep chronological order for readability
    results.sort(key=lambda r: r["_dt"])
    return results, branch_descriptions


def print_results(results):
    if not results:
        print("  (no matching entries)")
        return
    print(f"  {'timestamp':<20} {'user':<10} {'ip':<15} {'event':<12} status")
    print(f"  {'-'*20} {'-'*10} {'-'*15} {'-'*12} ------")
    for row in results:
        print(f"  {row['timestamp']:<20} {row['user']:<10} {row['ip']:<15} "
              f"{row['event']:<12} {row['status']}")


# ---------------------------------------------------------------------
# 4. CLI DEMO LOOP
# ---------------------------------------------------------------------

EXAMPLE_QUERIES = [
    "show all failed logins",
    "show all logins after 2am",
    "show all logins between 2am and 5am",
    "show all failed logins after 2am",
    "show all logins from user jdoe",
    "show all failed logins from ip 10.0.0.5",
    "show all logins not from user jdoe",
    "show all failed logins or file_delete events",
]

def main():
    logs = load_logs("sample_logs.csv")
    print(f"Loaded {len(logs)} log entries from sample_logs.csv\n")
    print("Example queries you can try:")
    for ex in EXAMPLE_QUERIES:
        print(f"  - {ex}")
    print("\nType a query (or 'quit' to exit):\n")

    while True:
        try:
            query = input("> ").strip()
        except EOFError:
            break
        if not query:
            continue
        if query.lower() in ("quit", "exit"):
            break

        results, branch_descriptions = run_query(logs, query)
        desc_str = " OR ".join(
            "(" + " AND ".join(d) + ")" if d else "(unrecognized)"
            for d in branch_descriptions
        )
        print(f"  Parsed as: {desc_str}")
        print(f"  {len(results)} match(es):")
        print_results(results)
        print()


if __name__ == "__main__":
    main()