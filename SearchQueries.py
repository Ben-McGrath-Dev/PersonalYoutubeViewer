import argparse
import re
import shlex
import sys
import time
from pathlib import Path


SEPARATOR = "=" * 80

FIELD_RE = re.compile(
    r"^(Video uploader|Date uploaded|Name|Video ID):\s*(.*)$",
    re.IGNORECASE,
)

DEFAULT_FILE = "youtube_videos_small.txt"
DEFAULT_LIMIT = 50


def iter_records(path: Path):
    """
    Stream records from a youtube_videos_small.txt-style file.

    This avoids loading the entire file into memory.
    """

    current = None
    description_lines = []
    in_description = False

    with path.open(
        "r",
        encoding="utf-8",
        errors="replace",
    ) as f:
        for raw_line in f:
            line = raw_line.rstrip("\r\n")

            if line == SEPARATOR:
                if current:
                    current["description"] = "\n".join(
                        description_lines
                    ).rstrip()

                    yield current

                current = {}
                description_lines = []
                in_description = False
                continue

            if current is None:
                continue

            if in_description:
                description_lines.append(line)
                continue

            if line.lower() == "video description:":
                in_description = True
                continue

            match = FIELD_RE.match(line)

            if not match:
                continue

            key, value = match.groups()
            key = key.lower()

            if key == "video uploader":
                current["uploader"] = value

            elif key == "date uploaded":
                current["date"] = value

            elif key == "name":
                current["name"] = value

            elif key == "video id":
                current["id"] = value

    if current:
        current["description"] = "\n".join(
            description_lines
        ).rstrip()

        yield current


def load_records(path: Path):
    """
    Load all records once for fast repeated interactive searching.
    """

    return list(
        iter_records(path)
    )


def normalize(value: str, case_sensitive: bool):
    if case_sensitive:
        return value

    return value.lower()


def field_text(record, field):
    if field == "all":
        return "\n".join(
            [
                record.get("uploader", ""),
                record.get("date", ""),
                record.get("name", ""),
                record.get("id", ""),
                record.get("description", ""),
            ]
        )

    return record.get(field, "")


def compile_patterns(
    terms,
    case_sensitive,
):
    flags = (
        0
        if case_sensitive
        else re.IGNORECASE
    )

    patterns = []

    for term in terms:
        try:
            patterns.append(
                re.compile(
                    term,
                    flags,
                )
            )

        except re.error as error:
            raise ValueError(
                f"Invalid regex {term!r}: {error}"
            ) from error

    return patterns


def matches(
    record,
    terms,
    field,
    mode,
    case_sensitive,
    regex,
    compiled_patterns=None,
):
    haystack = field_text(
        record,
        field,
    )

    if regex:
        patterns = (
            compiled_patterns
            if compiled_patterns is not None
            else compile_patterns(
                terms,
                case_sensitive,
            )
        )

        checks = [
            bool(
                pattern.search(
                    haystack
                )
            )
            for pattern in patterns
        ]

    else:
        normalized_haystack = normalize(
            haystack,
            case_sensitive,
        )

        checks = [
            normalize(
                term,
                case_sensitive,
            )
            in normalized_haystack
            for term in terms
        ]

    if mode == "and":
        return all(checks)

    return any(checks)


def format_record(
    record,
    show_description=False,
    compact=False,
    index=None,
):
    if compact:
        prefix = (
            f"{index}. "
            if index is not None
            else ""
        )

        return (
            f"{prefix}"
            f"{record.get('name', '')}"
            " | "
            f"{record.get('uploader', '')}"
            " | "
            f"{record.get('date', '')}"
            " | "
            f"{record.get('id', '')}"
        )

    lines = []

    if index is not None:
        lines.append(
            f"[{index}]"
        )

    video_id = record.get(
        "id",
        "",
    )

    lines.extend(
        [
            f"Name: {record.get('name', '')}",
            f"Uploader: {record.get('uploader', '')}",
            f"Date: {record.get('date', '')}",
            f"Video ID: {video_id}",
            (
                "URL: "
                "https://www.youtube.com/watch?v="
                f"{video_id}"
            ),
        ]
    )

    if show_description:
        lines.append(
            "Description:"
        )

        lines.append(
            record.get(
                "description",
                "",
            )
        )

    return "\n".join(
        lines
    )


def search_records(
    records,
    terms,
    field="all",
    mode="and",
    case_sensitive=False,
    regex=False,
):
    compiled_patterns = None

    if regex:
        compiled_patterns = compile_patterns(
            terms,
            case_sensitive,
        )

    for record in records:
        if matches(
            record,
            terms,
            field,
            mode,
            case_sensitive,
            regex,
            compiled_patterns=compiled_patterns,
        ):
            yield record


def print_results(
    results,
    limit=DEFAULT_LIMIT,
    show_description=False,
    compact=False,
    ids_only=False,
    urls_only=False,
    count_only=False,
):
    total = len(results)

    if count_only:
        print(total)
        return

    if total == 0:
        print("No matches.")
        return

    if limit == 0:
        display_results = results
    else:
        display_results = results[: max(limit, 0)]

    for index, record in enumerate(
        display_results,
        start=1,
    ):
        if ids_only:
            print(
                record.get(
                    "id",
                    "",
                )
            )

        elif urls_only:
            print(
                "https://www.youtube.com/watch?v="
                f"{record.get('id', '')}"
            )

        else:
            if index > 1:
                print()

                if not compact:
                    print(
                        "-" * 80
                    )

            print(
                format_record(
                    record,
                    show_description=show_description,
                    compact=compact,
                    index=index,
                )
            )

    if not ids_only and not urls_only:
        print()

    if limit != 0 and total > len(display_results):
        print(
            f"Showing {len(display_results):,} of "
            f"{total:,} matches. "
            "Use limit 0 / --limit 0 to show all."
        )

    elif not ids_only and not urls_only:
        print(
            f"Matches: {total:,}"
        )


def parse_date_filter(value):
    value = value.strip()

    if not value:
        return None

    if not re.fullmatch(
        r"\d{4}(?:\d{2}(?:\d{2})?)?",
        value,
    ):
        raise ValueError(
            "Date filters must be YYYY, YYYYMM, or YYYYMMDD."
        )

    return value


def apply_date_filters(
    records,
    after=None,
    before=None,
):
    if not after and not before:
        return records

    filtered = []

    for record in records:
        date = record.get(
            "date",
            "",
        )

        if not date:
            continue

        if after:
            after_padded = after.ljust(
                8,
                "0",
            )

            if date < after_padded:
                continue

        if before:
            before_padded = before.ljust(
                8,
                "9",
            )

            if date > before_padded:
                continue

        filtered.append(
            record
        )

    return filtered


def print_banner(
    path,
    record_count,
    load_seconds=None,
):
    print()
    print(
        "=" * 72
    )
    print(
        "                PERSONAL YOUTUBE DATABASE SEARCH"
    )
    print(
        "=" * 72
    )
    print()
    print(
        f"File:   {path}"
    )
    print(
        f"Videos: {record_count:,}"
    )

    if load_seconds is not None:
        print(
            f"Loaded: {load_seconds:.2f}s"
        )

    print()


def print_interactive_help():
    print(
        """
Interactive commands:

  <search terms>
      Search all fields.
      Example:
          mattbatwings
          minecraft redstone

  /field <field>
      Search only one field.

      Fields:
          all
          name
          uploader
          id
          date
          description

      Example:
          /field uploader

  /mode <and|or>
      AND requires every search term.
      OR requires any search term.

  /regex <on|off>
      Enable or disable regular expression searching.

  /case <on|off>
      Enable or disable case-sensitive searching.

  /limit <number>
      Set maximum displayed results.
      0 means unlimited.

  /compact <on|off>
      Toggle one-line result output.

  /description <on|off>
      Toggle full description output.

  /after <YYYY|YYYYMM|YYYYMMDD|off>
      Only show videos on/after a date.

  /before <YYYY|YYYYMM|YYYYMMDD|off>
      Only show videos on/before a date.

  /status
      Show the current search configuration.

  /reset
      Restore default search settings.

  /reload
      Reload the file from disk.

  /help
      Show this help.

  /quit
  /exit
      Exit the program.

Search syntax:

  Terms are split like normal shell arguments, so quotes work.

      mattbatwings redstone
      "Mumbo Jumbo"
      "MrBeast Gaming" redstone

Examples:

  /field name
  redstone computer

  /field uploader
  "Mumbo Jumbo"

  /mode or
  mattbatwings purplers mumbo

  /regex on
  ^How .* Minecraft
"""
    )


def interactive_mode(path: Path):
    if not path.exists():
        print(
            f"Error: file not found: {path}",
            file=sys.stderr,
        )

        return 2

    started = time.perf_counter()

    records = load_records(
        path
    )

    load_seconds = (
        time.perf_counter()
        -
        started
    )

    settings = {
        "field": "all",
        "mode": "and",
        "regex": False,
        "case_sensitive": False,
        "limit": DEFAULT_LIMIT,
        "compact": True,
        "show_description": False,
        "after": None,
        "before": None,
    }

    print_banner(
        path,
        len(records),
        load_seconds,
    )

    print(
        "Type a search and press Enter."
    )
    print(
        "Type /help for commands or /quit to exit."
    )
    print()

    while True:
        try:
            raw = input(
                "Search > "
            ).strip()

        except (
            EOFError,
            KeyboardInterrupt,
        ):
            print()
            print(
                "Goodbye."
            )
            return 0

        if not raw:
            continue

        if raw.startswith("/"):
            command_line = (
                raw[1:]
            )

            try:
                parts = shlex.split(
                    command_line
                )

            except ValueError as error:
                print(
                    f"Command error: {error}"
                )
                print()
                continue

            if not parts:
                continue

            command = (
                parts[0]
                .lower()
            )

            args = parts[1:]

            if command in {
                "quit",
                "exit",
                "q",
            }:
                print(
                    "Goodbye."
                )
                return 0

            if command in {
                "help",
                "h",
                "?",
            }:
                print_interactive_help()
                continue

            if command == "status":
                print(
                    f"Field:       {settings['field']}"
                )
                print(
                    f"Mode:        {settings['mode'].upper()}"
                )
                print(
                    f"Regex:       {'ON' if settings['regex'] else 'OFF'}"
                )
                print(
                    f"Case:        "
                    f"{'sensitive' if settings['case_sensitive'] else 'insensitive'}"
                )
                print(
                    f"Limit:       {settings['limit']}"
                )
                print(
                    f"Compact:     {'ON' if settings['compact'] else 'OFF'}"
                )
                print(
                    f"Description: "
                    f"{'ON' if settings['show_description'] else 'OFF'}"
                )
                print(
                    f"After:       {settings['after'] or 'OFF'}"
                )
                print(
                    f"Before:      {settings['before'] or 'OFF'}"
                )
                print()
                continue

            if command == "reset":
                settings.update(
                    {
                        "field": "all",
                        "mode": "and",
                        "regex": False,
                        "case_sensitive": False,
                        "limit": DEFAULT_LIMIT,
                        "compact": True,
                        "show_description": False,
                        "after": None,
                        "before": None,
                    }
                )

                print(
                    "Search settings reset."
                )
                print()
                continue

            if command == "reload":
                started = time.perf_counter()

                records = load_records(
                    path
                )

                elapsed = (
                    time.perf_counter()
                    -
                    started
                )

                print(
                    f"Reloaded {len(records):,} videos "
                    f"in {elapsed:.2f}s."
                )
                print()
                continue

            if command == "field":
                if len(args) != 1:
                    print(
                        "Usage: /field "
                        "all|name|uploader|id|date|description"
                    )
                    print()
                    continue

                field = (
                    args[0]
                    .lower()
                )

                valid_fields = {
                    "all",
                    "name",
                    "uploader",
                    "id",
                    "date",
                    "description",
                }

                if field not in valid_fields:
                    print(
                        f"Unknown field: {field}"
                    )
                    print()
                    continue

                settings["field"] = field

                print(
                    f"Field set to: {field}"
                )
                print()
                continue

            if command == "mode":
                if (
                    len(args) != 1
                    or
                    args[0].lower()
                    not in {
                        "and",
                        "or",
                    }
                ):
                    print(
                        "Usage: /mode and|or"
                    )
                    print()
                    continue

                settings["mode"] = (
                    args[0].lower()
                )

                print(
                    f"Mode set to: {settings['mode'].upper()}"
                )
                print()
                continue

            if command in {
                "regex",
                "case",
                "compact",
                "description",
            }:
                if (
                    len(args) != 1
                    or
                    args[0].lower()
                    not in {
                        "on",
                        "off",
                    }
                ):
                    print(
                        f"Usage: /{command} on|off"
                    )
                    print()
                    continue

                enabled = (
                    args[0].lower()
                    == "on"
                )

                key_map = {
                    "regex": "regex",
                    "case": "case_sensitive",
                    "compact": "compact",
                    "description": "show_description",
                }

                settings[
                    key_map[command]
                ] = enabled

                print(
                    f"{command.capitalize()}: "
                    f"{'ON' if enabled else 'OFF'}"
                )
                print()
                continue

            if command == "limit":
                if len(args) != 1:
                    print(
                        "Usage: /limit <number>"
                    )
                    print()
                    continue

                try:
                    value = int(
                        args[0]
                    )

                except ValueError:
                    print(
                        "Limit must be a whole number."
                    )
                    print()
                    continue

                if value < 0:
                    print(
                        "Limit cannot be negative."
                    )
                    print()
                    continue

                settings["limit"] = value

                print(
                    f"Limit set to: {value}"
                )
                print()
                continue

            if command in {
                "after",
                "before",
            }:
                if len(args) != 1:
                    print(
                        f"Usage: /{command} "
                        "YYYY|YYYYMM|YYYYMMDD|off"
                    )
                    print()
                    continue

                value = (
                    args[0]
                    .strip()
                )

                if value.lower() == "off":
                    settings[command] = None

                    print(
                        f"{command.capitalize()} filter disabled."
                    )
                    print()
                    continue

                try:
                    parsed = parse_date_filter(
                        value
                    )

                except ValueError as error:
                    print(
                        f"Error: {error}"
                    )
                    print()
                    continue

                settings[command] = parsed

                print(
                    f"{command.capitalize()} set to: {parsed}"
                )
                print()
                continue

            print(
                f"Unknown command: /{command}"
            )
            print(
                "Type /help for available commands."
            )
            print()
            continue

        try:
            terms = shlex.split(
                raw
            )

        except ValueError as error:
            print(
                f"Search error: {error}"
            )
            print()
            continue

        if not terms:
            continue

        started = time.perf_counter()

        try:
            results = list(
                search_records(
                    records,
                    terms,
                    field=settings["field"],
                    mode=settings["mode"],
                    case_sensitive=settings["case_sensitive"],
                    regex=settings["regex"],
                )
            )

        except ValueError as error:
            print(
                f"Search error: {error}"
            )
            print()
            continue

        results = apply_date_filters(
            results,
            after=settings["after"],
            before=settings["before"],
        )

        elapsed = (
            time.perf_counter()
            -
            started
        )

        print()

        print_results(
            results,
            limit=settings["limit"],
            show_description=settings["show_description"],
            compact=settings["compact"],
        )

        print(
            f"Search time: {elapsed * 1000:.1f} ms"
        )
        print()


def command_line_mode(args):
    path = Path(
        args.file
    )

    if not path.exists():
        print(
            f"Error: file not found: {path}",
            file=sys.stderr,
        )

        return 2

    try:
        after = (
            parse_date_filter(
                args.after
            )
            if args.after
            else None
        )

        before = (
            parse_date_filter(
                args.before
            )
            if args.before
            else None
        )

    except ValueError as error:
        print(
            f"Error: {error}",
            file=sys.stderr,
        )

        return 2

    started = time.perf_counter()

    try:
        results = list(
            search_records(
                iter_records(path),
                args.terms,
                field=args.field,
                mode=args.mode,
                case_sensitive=args.case_sensitive,
                regex=args.regex,
            )
        )

    except ValueError as error:
        print(
            f"Error: {error}",
            file=sys.stderr,
        )

        return 2

    results = apply_date_filters(
        results,
        after=after,
        before=before,
    )

    elapsed = (
        time.perf_counter()
        -
        started
    )

    print_results(
        results,
        limit=args.limit,
        show_description=args.description,
        compact=args.compact,
        ids_only=args.ids_only,
        urls_only=args.urls_only,
        count_only=args.count,
    )

    if args.timing and not args.count:
        print(
            f"Search time: {elapsed * 1000:.1f} ms",
            file=sys.stderr,
        )

    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Fast CLI and interactive search for "
            "youtube_videos_small.txt-style files."
        )
    )

    parser.add_argument(
        "terms",
        nargs="*",
        help=(
            "Search term(s). "
            "If omitted, interactive mode starts."
        ),
    )

    parser.add_argument(
        "-f",
        "--file",
        default=DEFAULT_FILE,
        help=(
            "Input file "
            f"(default: {DEFAULT_FILE})"
        ),
    )

    parser.add_argument(
        "--field",
        choices=[
            "all",
            "name",
            "uploader",
            "id",
            "date",
            "description",
        ],
        default="all",
        help=(
            "Limit search to one field "
            "(default: all)"
        ),
    )

    parser.add_argument(
        "--mode",
        choices=[
            "and",
            "or",
        ],
        default="and",
        help=(
            "Require all terms or any term "
            "(default: and)"
        ),
    )

    parser.add_argument(
        "--case-sensitive",
        action="store_true",
        help="Use case-sensitive matching",
    )

    parser.add_argument(
        "-r",
        "--regex",
        action="store_true",
        help=(
            "Treat search terms as "
            "regular expressions"
        ),
    )

    parser.add_argument(
        "-n",
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=(
            "Maximum results to print "
            f"(default: {DEFAULT_LIMIT}, 0 = unlimited)"
        ),
    )

    parser.add_argument(
        "--description",
        action="store_true",
        help="Print full descriptions",
    )

    parser.add_argument(
        "-c",
        "--compact",
        action="store_true",
        help="Use one-line result format",
    )

    parser.add_argument(
        "--count",
        action="store_true",
        help=(
            "Only print the number "
            "of matching videos"
        ),
    )

    parser.add_argument(
        "--ids-only",
        action="store_true",
        help="Print only matching video IDs",
    )

    parser.add_argument(
        "--urls-only",
        action="store_true",
        help="Print only matching YouTube URLs",
    )

    parser.add_argument(
        "--after",
        help=(
            "Only show videos on/after "
            "YYYY, YYYYMM, or YYYYMMDD"
        ),
    )

    parser.add_argument(
        "--before",
        help=(
            "Only show videos on/before "
            "YYYY, YYYYMM, or YYYYMMDD"
        ),
    )

    parser.add_argument(
        "--timing",
        action="store_true",
        help="Print search timing information",
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.limit < 0:
        parser.error(
            "--limit cannot be negative"
        )

    if not args.terms:
        return interactive_mode(
            Path(
                args.file
            )
        )

    return command_line_mode(
        args
    )


if __name__ == "__main__":
    raise SystemExit(
        main()
    )