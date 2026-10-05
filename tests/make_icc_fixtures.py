#!/usr/bin/env python3
"""Write tests/fixtures/icc: JPEGs carrying an ICC profile in APP2 "ICC_PROFILE" segments,
in every arrangement libjpeg-turbo's jpeg_read_icc_profile accepts or refuses: split in
order and out of order, repeated, missing or zero sequence numbers, disagreeing counts, empty
parts, other APP2 segments, and segments between and after the scans. Made from
tests/fixtures' b444_7x9.jpg (baseline) and p420_37x35.jpg (progressive). expected.txt is
what libjpeg-turbo joins from each (luce-browser-tools/oracles/luce-jpeg/icc)."""
import random
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "fixtures"
OUT = ROOT / "icc"


def app2(payload):
    return b"\xff\xe2" + struct.pack(">H", len(payload) + 2) + payload


def icc_segment(sequence, count, part):
    return app2(b"ICC_PROFILE\0" + bytes([sequence, count]) + part)


def split(profile, parts):
    size = (len(profile) + parts - 1) // parts
    return [profile[i * size:(i + 1) * size] for i in range(parts)]


def insert_after_soi(jpeg, segments):
    return jpeg[:2] + b"".join(segments) + jpeg[2:]


def insert_before_eoi(jpeg, segments):
    assert jpeg.endswith(b"\xff\xd9")
    return jpeg[:-2] + b"".join(segments) + jpeg[-2:]


def insert_after_first_scan(jpeg, segments):
    """Before the second SOS marker of a progressive file."""
    first = jpeg.index(b"\xff\xda")
    second = jpeg.index(b"\xff\xda", first + 2)
    return jpeg[:second] + b"".join(segments) + jpeg[second:]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rng = random.Random(2026)
    profile = bytes(rng.randrange(256) for _ in range(1000))
    baseline = (ROOT / "b444_7x9.jpg").read_bytes()
    progressive = (ROOT / "p420_37x35.jpg").read_bytes()
    a, b, c = split(profile, 3)
    files = {
        "icc-one.jpg": insert_after_soi(baseline, [icc_segment(1, 1, profile)]),
        "icc-three.jpg": insert_after_soi(baseline, [icc_segment(1, 3, a), icc_segment(2, 3, b), icc_segment(3, 3, c)]),
        "icc-reordered.jpg": insert_after_soi(baseline, [icc_segment(3, 3, c), icc_segment(1, 3, a), icc_segment(2, 3, b)]),
        "icc-duplicate.jpg": insert_after_soi(baseline, [icc_segment(1, 3, a), icc_segment(1, 3, a), icc_segment(2, 3, b), icc_segment(3, 3, c)]),
        "icc-missing.jpg": insert_after_soi(baseline, [icc_segment(1, 3, a), icc_segment(3, 3, c)]),
        "icc-counts-differ.jpg": insert_after_soi(baseline, [icc_segment(1, 3, a), icc_segment(2, 2, b), icc_segment(3, 3, c)]),
        "icc-sequence-zero.jpg": insert_after_soi(baseline, [icc_segment(0, 1, profile)]),
        "icc-sequence-past-count.jpg": insert_after_soi(baseline, [icc_segment(2, 1, profile)]),
        "icc-empty-parts.jpg": insert_after_soi(baseline, [icc_segment(1, 2, b""), icc_segment(2, 2, b"")]),
        "icc-one-empty-part.jpg": insert_after_soi(baseline, [icc_segment(1, 2, b""), icc_segment(2, 2, profile)]),
        "icc-other-app2.jpg": insert_after_soi(baseline, [app2(b"MPF\0\0\0\0\0"), app2(b"ICC_PROFIL"), icc_segment(1, 1, profile)]),
        "icc-short-segment.jpg": insert_after_soi(baseline, [app2(b"ICC_PROFILE\0\1"), icc_segment(1, 1, profile)]),
        "icc-zero-count.jpg": insert_after_soi(baseline, [icc_segment(1, 0, profile)]),
        "icc-before-eoi.jpg": insert_before_eoi(baseline, [icc_segment(1, 1, profile)]),
        "icc-between-scans.jpg": insert_after_first_scan(progressive, [icc_segment(1, 1, profile)]),
        "icc-split-across-scans.jpg": insert_after_first_scan(insert_after_soi(progressive, [icc_segment(1, 2, a)]), [icc_segment(2, 2, b)]),
    }
    for name, data in sorted(files.items()):
        (OUT / name).write_bytes(data)
    print(f"{len(files)} JPEGs")


if __name__ == "__main__":
    main()
