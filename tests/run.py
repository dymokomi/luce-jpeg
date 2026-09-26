#!/usr/bin/env python3
"""luce-jpeg's gate: the module's test blocks, then the decoder drivers in native
and C modes against the fixtures:

- every fixture decodes through the Raster API to exactly the samples of the
  reference float decoder, on both backends (tests/fixtures/golden.txt);
- decode_rgb8, decode_rgba8, decode_rows and decode_rows_at (the file read in
  pieces) give those same samples, on one thread and on several;
- scaled decodes (1/2, 1/4, 1/8) have the scaled size, and with Pillow present
  stay within 4 of libjpeg's reduced decodes, as full-size decodes stay within 4
  of libjpeg's (except 3:1 and 4:1 sampling, which libjpeg replicates);
- truncated and corrupted files fail cleanly, never crash or hang;
- the encoder gives the same bytes on one thread, on all, and streamed, for every
  sampling, restart and table option; its files decode (here and, with Pillow, in
  libjpeg identically within 4) close to the source.
"""
import hashlib, io, os, random, struct, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(os.environ.get("LUCE_BASE", ROOT.parent / "luce-base/build/luce-base")).resolve()
MODES = [["--native"], ["--backend=c"]]
env = dict(os.environ, LUCE_BASE=str(BASE), LUCE_STD=str((ROOT.parent / "luce-base/src/std").resolve()))
FIXTURES = sorted((ROOT / "tests/fixtures").glob("*.jpg"))
GOLDEN = {}
for line in (ROOT / "tests/fixtures/golden.txt").read_text().splitlines():
    if line and not line.startswith("#"):
        digest, name = line.split("  ")
        GOLDEN[name] = digest
# libjpeg replicates 3:1 and 4:1 chroma where this decoder interpolates.
REPLICATED = {"s32.jpg", "s411.jpg"}

try:
    from PIL import Image
except ImportError:
    Image = None


def run(command, **options):
    return subprocess.run([str(x) for x in command], env=env, cwd=ROOT, timeout=300, **options)


def fail(message):
    raise SystemExit(f"FAIL {message}")


def read_raw(path):
    data = path.read_bytes()
    width, height, channels = struct.unpack_from("<III", data)
    return width, height, channels, data[12:]


def as_rgb(channels, pixels):
    """Samples as RGB triples: gray repeated, alpha dropped."""
    if channels == 3:
        return pixels
    if channels == 1:
        return bytes(v for v in pixels for _ in range(3))
    return bytes(b for i, b in enumerate(pixels) if i % 4 != 3)


def reference(path, scale):
    with Image.open(path) as image:
        width, height = image.size
        if scale > 1:
            image.draft(image.mode, (max(1, width // scale), max(1, height // scale)))
        return image.size, image.convert("RGB").tobytes()


def check_drivers(tmp, flags):
    dump, scaled = tmp / "dump", tmp / "scaled"
    run([BASE, "build", ROOT / "tests/dump.lucb", *flags, "-o", dump], check=True)
    run([BASE, "build", ROOT / "tests/scaled.lucb", *flags, "-o", scaled], check=True)
    raw, out = tmp / "raw", tmp / "out"
    compared = 0
    for fixture in FIXTURES:
        name = fixture.name
        if run([dump, fixture, raw]).returncode != 0:
            fail(f"{name}: the Raster decode failed")
        if hashlib.sha256(raw.read_bytes()).hexdigest() != GOLDEN[name]:
            fail(f"{name}: Raster samples differ from the reference decoder")
        width, height, channels, samples = read_raw(raw)
        expected = as_rgb(channels, samples)
        for mode, threads in [("rgb", 1), ("rgba", 0), ("rows", 0), ("rgb", 3), ("at", 0)]:
            if run([scaled, fixture, out, 1, mode, threads]).returncode != 0:
                fail(f"{name}: {mode} decode on {threads} threads failed")
            w, h, pixel, pixels = read_raw(out)
            if (w, h) != (width, height) or as_rgb(pixel, pixels) != expected:
                fail(f"{name}: {mode} on {threads} threads differs from the Raster decode")
            if mode == "rgba" and any(pixels[i] != 255 for i in range(3, len(pixels), 4)):
                fail(f"{name}: alpha is not opaque")
        if Image and name not in REPLICATED:
            size, ref = reference(fixture, 1)
            worst = max(abs(a - b) for a, b in zip(ref, expected))
            if worst > 4:
                fail(f"{name}: differs from libjpeg by {worst}")
        for scale in [2, 4, 8]:
            if run([scaled, fixture, out, scale, "rgb"]).returncode != 0:
                fail(f"{name}: 1/{scale} decode failed")
            w, h, pixel, pixels = read_raw(out)
            if (w, h) != (-(-width // scale), -(-height // scale)):
                fail(f"{name}: 1/{scale} decode is {w}x{h}")
            if run([scaled, fixture, out, scale, "rows", 2]).returncode != 0 or read_raw(out)[3] != pixels:
                fail(f"{name}: 1/{scale} rows differ from decode_rgb8")
            if run([scaled, fixture, out, scale, "at", 2]).returncode != 0 or read_raw(out)[3] != pixels:
                fail(f"{name}: 1/{scale} rows read in pieces differ from decode_rgb8")
            if Image:
                size, ref = reference(fixture, scale)
                # Pillow's draft cannot ask for every ceil-rounded size of tiny pictures.
                if size == (w, h):
                    worst = max(abs(a - b) for a, b in zip(ref, pixels))
                    if worst > 4:
                        fail(f"{name}: 1/{scale} differs from libjpeg by {worst}")
                    compared += 1
    print(f"ok    {len(FIXTURES)} fixtures identical to the reference decoder through every API"
          + (f"; {compared} scaled decodes within 4 of libjpeg" if Image else "; Pillow absent, libjpeg comparisons skipped"))
    # Damaged files: every truncation point of a few fixtures and random byte
    # changes must end in a clean error or a decode, never a crash or a hang.
    rng = random.Random(7)
    damaged = 0
    for name in ["b420_37x35.jpg", "p420_37x35.jpg", "restart420.jpg", "mt_b420.jpg", "mt_restart.jpg", "mt_p420.jpg"]:
        data = (ROOT / "tests/fixtures" / name).read_bytes()
        cases = [data[:n] for n in range(2, len(data), max(1, len(data) // 60))]
        for _ in range(40):
            changed = bytearray(data)
            for _ in range(rng.randrange(1, 4)):
                changed[rng.randrange(2, len(changed))] = rng.randrange(256)
            cases.append(bytes(changed))
        for case in cases:
            (tmp / "bad.jpg").write_bytes(case)
            for command in [[dump, tmp / "bad.jpg", raw], [scaled, tmp / "bad.jpg", out, 1, "rgba"], [scaled, tmp / "bad.jpg", out, 2, "rows"], [scaled, tmp / "bad.jpg", out, 1, "at"]]:
                result = run(command, capture_output=True)
                if result.returncode not in (0, 1):
                    fail(f"{name}: a damaged file ended the process with {result.returncode}")
                damaged += 1
    print(f"ok    {damaged} decodes of damaged files ended cleanly")
    check_large(tmp, scaled)
    check_encoder(tmp, flags, scaled)


def check_large(tmp, scaled):
    """Files of several megabytes, whose windows slide many times, decode read in
    pieces as they decode whole: baseline, restarts, progressive."""
    if not Image:
        print("skip  large files read in pieces: Pillow absent")
        return
    rng = random.Random(11)
    picture = Image.frombytes("RGB", (1600, 1200), bytes(rng.randrange(256) for _ in range(1600 * 1200 * 3)))
    out, whole = tmp / "out", tmp / "whole"
    for name, options in [("baseline", {}), ("restart", {"restart_marker_blocks": 5}), ("progressive", {"progressive": True}),
                          ("progressive restart", {"progressive": True, "restart_marker_blocks": 3, "subsampling": 2})]:
        path = tmp / "large.jpg"
        picture.save(path, "JPEG", quality=95, **options)
        if run([scaled, path, whole, 1, "rows", 0]).returncode != 0 or run([scaled, path, out, 1, "at", 0]).returncode != 0:
            fail(f"large {name}: does not decode")
        if read_raw(out)[3] != read_raw(whole)[3]:
            fail(f"large {name}: read in pieces differs from the file whole")
    print("ok    large files read in pieces decode as the file whole")


def check_encoder(tmp, flags, scaled):
    encode = tmp / "encode"
    run([BASE, "build", ROOT / "tests/encode.lucb", *flags, "-o", encode], check=True)
    source, decoded = tmp / "source", tmp / "decoded"
    checked = 0
    for name in ["mt_b420.jpg", "mt_b444.jpg", "b444_37x35.jpg", "rgb.jpg", "b420_1x1.jpg"]:
        fixture = ROOT / "tests/fixtures" / name
        run([scaled, fixture, source, 1, "rgb"], check=True)
        original = read_raw(source)[3]
        for sampling, options in [("420", "-"), ("444", "r"), ("422", "o"), ("420", "ro")]:
            outputs = []
            for mode, threads in [("rgba", 0), ("rgba", 1), ("stream", 0)]:
                out = tmp / f"{mode}{threads}.jpg"
                if run([encode, fixture, out, 1, mode, 90, sampling, options, threads], capture_output=True).returncode != 0:
                    fail(f"{name}: {mode} {sampling} {options} encode failed")
                outputs.append(out.read_bytes())
            if outputs[1] != outputs[0] or outputs[2] != outputs[0]:
                fail(f"{name}: {sampling} {options} differs between threads or streaming")
            encoded = tmp / "rgba0.jpg"
            if run([scaled, encoded, decoded, 1, "rgb"]).returncode != 0:
                fail(f"{name}: {sampling} {options} output does not decode")
            pixels = read_raw(decoded)[3]
            mean = sum(abs(a - b) for a, b in zip(original, pixels)) / len(pixels)
            # As close to the source as libjpeg's encoding at the same settings.
            bound = 8.0
            if Image:
                width, height = read_raw(source)[:2]
                picture = Image.frombytes("RGB", (width, height), original)
                ours = io.BytesIO()
                picture.save(ours, "JPEG", quality=90, subsampling={"444": 0, "422": 1, "420": 2}[sampling])
                with Image.open(io.BytesIO(ours.getvalue())) as image:
                    theirs = image.convert("RGB").tobytes()
                bound = sum(abs(a - b) for a, b in zip(original, theirs)) / len(theirs) + 0.5
            if mean > bound:
                fail(f"{name}: {sampling} {options} is {mean:.2f} from the source on average, over {bound:.2f}")
            if Image:
                with Image.open(encoded) as image:
                    reference = image.convert("RGB").tobytes()
                worst = max(abs(a - b) for a, b in zip(reference, pixels))
                if worst > 4:
                    fail(f"{name}: {sampling} {options} decodes {worst} apart in libjpeg")
            checked += 1
        for mode in ["gray", "raster"]:
            if run([encode, fixture, tmp / "other.jpg", 1, mode, 90], capture_output=True).returncode != 0 or run([scaled, tmp / "other.jpg", decoded, 1, "rgb"]).returncode != 0:
                fail(f"{name}: {mode} encode does not round-trip")
            checked += 1
    print(f"ok    {checked} encodings identical across threads and streaming, decoding close to their source")


for flags in MODES:
    run([BASE, "test", ROOT / "src/luce_jpeg/jpeg", *flags], check=True)
    with tempfile.TemporaryDirectory(prefix="luce-jpeg-") as tmp:
        check_drivers(Path(tmp), flags)
print("PASS luce-jpeg")
