# Log Query DSL

A small domain-specific language (DSL) and interpreter that lets an
investigator query a log file using plain, English-like syntax
instead of SQL or manual scripting.

## Example

```
> show all failed logins after 2am
  Parsed as: (status == failed AND event == login AND hour >= 2)
  8 match(es):
  timestamp            user       ip              event        status
  -------------------- ---------- --------------- ------------ ------
  2024-01-15 02:00:01  jdoe       192.168.1.10    login        failed
  ...
```

## Supported query patterns

- `show all failed logins`
- `show all successful logins`
- `show all logins after 2am`
- `show all logins before 6am`
- `show all logins between 2am and 5am`
- `show all logins from user jdoe`
- `show all logins from ip 10.0.0.5`
- `show all logins not from user jdoe`
- `show all logins excluding ip 10.0.0.5`
- `show all failed logins or file_delete events` (OR across conditions)
- Any combination of the above (e.g. status + time + field filter together)

## How it works

1. **Split** — the query is split on the word "or" into independent branches.
2. **Parse** — each branch is scanned with regex to extract status, event
   type, a time bound or range, a field filter (user/ip), and negation.
3. **Compile** — every recognized piece becomes a small filter function
   (`row -> True/False`).
4. **Execute** — filters within a branch combine with AND; branches
   combine with OR (set union) over every row in the log file.

This is intentionally regex-based rather than a formal grammar/AST —
for a time-boxed MVP, proving the full parse → compile → execute
pipeline mattered more than parser sophistication. The architecture
is built so that adding a new query shape only means adding one more
regex + one more filter function; the pipeline itself never changes.

## Running it

```
python3 log_dsl.py
```

Requires Python 3.6+, no external dependencies (uses only `csv`, `re`,
`datetime` from the standard library).

## With more time, we'd add

- A proper tokenizer/AST instead of regex, to support arbitrarily
  nested conditions
- Aggregation queries (e.g. "count failed logins by user")
- Fuzzy/typo-tolerant matching on field values