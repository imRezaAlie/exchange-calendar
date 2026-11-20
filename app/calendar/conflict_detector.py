"""Detect overlapping meetings. This module does not talk to Exchange or Qt."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

from app.calendar.date_utils import as_utc, format_minutes, format_time_span
from app.models import Meeting

_ELIGIBLE_BUSY = {"busy", "oof", "working_elsewhere", "no_data"}


@dataclass(frozen=True)
class ConflictPolicy:
    """Controls which calendar entries participate in overlap detection.

    Back-to-back meetings are never conflicts: an overlap requires the shared
    interval to have a positive duration. All-day informational events are
    excluded unless ``include_all_day`` is set. Cancelled and free entries are
    ignored. Tentative entries are included only when requested. A declined
    response is ignored because the mailbox owner is not attending.
    """

    include_tentative: bool = True
    include_all_day: bool = False
    ignore_cancelled: bool = True
    ignore_free: bool = True


@dataclass(frozen=True)
class Overlap:
    first_id: str
    second_id: str
    start: datetime
    end: datetime

    @property
    def minutes(self) -> int:
        seconds = (self.end - self.start).total_seconds()
        if seconds <= 0:
            return 0
        whole = int(seconds // 60)
        return whole if whole > 0 else 1

    def other(self, uid: str) -> str:
        if uid == self.first_id:
            return self.second_id
        if uid == self.second_id:
            return self.first_id
        raise KeyError(uid)

    def involves(self, uid: str) -> bool:
        return uid in (self.first_id, self.second_id)


@dataclass
class ConflictReport:
    overlaps: list[Overlap] = field(default_factory=list)
    by_meeting: dict[str, list[Overlap]] = field(default_factory=dict)

    def has_conflict(self, uid: str) -> bool:
        return bool(self.by_meeting.get(uid))

    def conflicting_ids(self) -> set[str]:
        return set(self.by_meeting)

    def for_meeting(self, uid: str) -> list[Overlap]:
        return list(self.by_meeting.get(uid, []))

    def cluster_containing(self, uid: str) -> list[str]:
        if uid not in self.by_meeting:
            return []
        seen: set[str] = set()
        stack = [uid]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            for overlap in self.by_meeting.get(current, []):
                stack.append(overlap.other(current))
        return sorted(seen)

    def overlaps_among(self, ids: Iterable[str]) -> list[Overlap]:
        wanted = set(ids)
        return [
            overlap
            for overlap in self.overlaps
            if overlap.first_id in wanted and overlap.second_id in wanted
        ]


def is_eligible(meeting: Meeting, policy: ConflictPolicy) -> bool:
    if as_utc(meeting.end) <= as_utc(meeting.start):
        return False
    if policy.ignore_cancelled and meeting.is_cancelled:
        return False
    if (meeting.response_status or "").lower() == "declined":
        return False
    if meeting.is_all_day and not policy.include_all_day:
        return False
    status = (meeting.busy_status or "no_data").lower()
    if policy.ignore_free and status == "free":
        return False
    if status == "tentative":
        return policy.include_tentative
    return status in _ELIGIBLE_BUSY or status == ""


def detect_conflicts(
    meetings: Sequence[Meeting],
    policy: ConflictPolicy | None = None,
) -> ConflictReport:
    """Return each unique overlapping pair.

    Comparison uses timezone-aware instants, so daylight-saving transitions and
    meetings that cross midnight are handled by absolute time rather than by
    clock-face subtraction. Recurring occurrences are ordinary meetings with
    their own start and end.
    """
    active_policy = policy or ConflictPolicy()
    eligible = [meeting for meeting in meetings if is_eligible(meeting, active_policy)]
    eligible.sort(key=lambda meeting: (as_utc(meeting.start), as_utc(meeting.end), meeting.uid))
    seen_pairs: set[tuple[str, str]] = set()
    overlaps: list[Overlap] = []
    for index, left in enumerate(eligible):
        for right in eligible[index + 1 :]:
            if as_utc(right.start) >= as_utc(left.end):
                break
            if left.uid == right.uid:
                continue
            overlap_start = left.start if as_utc(left.start) >= as_utc(right.start) else right.start
            overlap_end = left.end if as_utc(left.end) <= as_utc(right.end) else right.end
            if as_utc(overlap_start) >= as_utc(overlap_end):
                continue
            pair = tuple(sorted((left.uid, right.uid)))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            first, second = (
                (left, right)
                if (as_utc(left.start), left.uid) <= (as_utc(right.start), right.uid)
                else (right, left)
            )
            overlaps.append(
                Overlap(
                    first_id=first.uid,
                    second_id=second.uid,
                    start=overlap_start,
                    end=overlap_end,
                )
            )
    overlaps.sort(key=lambda item: (item.start, item.end, item.first_id, item.second_id))
    by_meeting: dict[str, list[Overlap]] = {}
    for overlap in overlaps:
        by_meeting.setdefault(overlap.first_id, []).append(overlap)
        by_meeting.setdefault(overlap.second_id, []).append(overlap)
    return ConflictReport(overlaps=overlaps, by_meeting=by_meeting)


def common_overlap(meetings: Sequence[Meeting]) -> tuple[datetime, datetime] | None:
    if len(meetings) < 2:
        return None
    start = meetings[0].start
    end = meetings[0].end
    for meeting in meetings[1:]:
        if as_utc(meeting.start) > as_utc(start):
            start = meeting.start
        if as_utc(meeting.end) < as_utc(end):
            end = meeting.end
    if as_utc(start) < as_utc(end):
        return start, end
    return None


def _subject(meeting: Meeting) -> str:
    return (meeting.subject or "").strip() or "(No subject)"


def format_conflict_popup(
    meeting: Meeting,
    report: ConflictReport,
    meetings_by_id: dict[str, Meeting],
    tz: ZoneInfo,
) -> str:
    """Plain-text conflict report for the details dialog."""
    cluster_ids = report.cluster_containing(meeting.uid)
    cluster = [meetings_by_id[uid] for uid in cluster_ids if uid in meetings_by_id]
    cluster.sort(key=lambda item: (item.start, item.end, item.subject.lower(), item.uid))
    if len(cluster) < 2:
        return ""
    lines = ["Meeting Conflict Detected", ""]
    if len(cluster) == 2:
        labels = ("A", "B")
        for label, item in zip(labels, cluster):
            lines.append(f"Meeting {label}:")
            lines.append(_subject(item))
            lines.append(format_time_span(item.start, item.end, tz, item.is_all_day))
            lines.append("")
        overlap = report.overlaps_among(cluster_ids)
        if overlap:
            window = overlap[0]
            lines.append("Conflict Window:")
            lines.append(format_time_span(window.start, window.end, tz))
            lines.append("")
            lines.append("Total Overlap:")
            lines.append(format_minutes(window.minutes))
        return "\n".join(lines).rstrip()

    for index, item in enumerate(cluster):
        label = chr(ord("A") + index) if index < 26 else str(index + 1)
        lines.append(f"Meeting {label}:")
        lines.append(_subject(item))
        lines.append(format_time_span(item.start, item.end, tz, item.is_all_day))
        lines.append("")
    lines.append("Conflict windows:")
    for overlap in report.overlaps_among(cluster_ids):
        left = meetings_by_id.get(overlap.first_id)
        right = meetings_by_id.get(overlap.second_id)
        left_name = _subject(left) if left else overlap.first_id
        right_name = _subject(right) if right else overlap.second_id
        lines.append(
            f"{left_name} ∩ {right_name}: "
            f"{format_time_span(overlap.start, overlap.end, tz)} "
            f"({format_minutes(overlap.minutes)})"
        )
    shared = common_overlap(cluster)
    lines.append("")
    if shared is not None:
        lines.append("Common overlap:")
        lines.append(format_time_span(shared[0], shared[1], tz))
        seconds = (shared[1] - shared[0]).total_seconds()
        whole = int(seconds // 60)
        minutes = whole if whole > 0 else 1
        lines.append("")
        lines.append("Total Overlap:")
        lines.append(format_minutes(minutes))
    else:
        lines.append("These meetings do not all share one common interval.")
        lines.append("Each overlapping pair is listed above.")
    return "\n".join(lines).rstrip()


def conflict_lines(
    meeting: Meeting,
    report: ConflictReport,
    meetings_by_id: dict[str, Meeting],
) -> tuple[str, str]:
    overlaps = report.for_meeting(meeting.uid)
    if not overlaps:
        return "", ""
    names: list[str] = []
    for overlap in overlaps:
        other = meetings_by_id.get(overlap.other(meeting.uid))
        names.append(_subject(other) if other else "another meeting")
    if len(names) == 1:
        title = f"CONFLICT with {names[0]}"
    elif len(names) == 2:
        title = f"CONFLICT with {names[0]} and {names[1]}"
    else:
        title = f"CONFLICT with {names[0]}, {names[1]} +{len(names) - 2}"
    largest = max(overlaps, key=lambda item: (item.minutes, item.start))
    detail = f"Overlap: {format_minutes(largest.minutes)}"
    if len(overlaps) > 1:
        detail += f" (largest of {len(overlaps)})"
    return title, detail
