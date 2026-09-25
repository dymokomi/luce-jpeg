#!/usr/bin/env python3
"""Regenerate tests/fixtures: small JPEGs covering every coding path, made by
Pillow, libjpeg-turbo's cjpeg and TurboJPEG (for YCCK). The goldens in
tests/fixtures/golden.txt were taken from the reference float decoder (luce-jpeg
1b14c8a) and must not be regenerated with a changed decoder."""
import ctypes, random, subprocess, tempfile
from pathlib import Path
from PIL import Image

OUT = Path(__file__).resolve().parent / "fixtures"
rng = random.Random(74)

def picture(w, h, mode="RGB"):
    """Smooth gradients with a little noise and a hard edge: real JPEG statistics."""
    im = Image.new("RGB", (w, h))
    px = im.load()
    for y in range(h):
        for x in range(w):
            edge = 90 if x > w * 0.6 else 0
            px[x, y] = tuple(max(0, min(255, int(v + rng.gauss(0, 6)))) for v in
                             (x * 255 // max(1, w - 1), (y * 200 // max(1, h - 1) + edge) % 256, (x + y) * 3 % 256))
    return im.convert(mode)

def noise(w, h, mode="RGB"):
    return Image.frombytes(mode, (w, h), bytes(rng.randrange(256) for _ in range(w * h * len(mode))))

def cjpeg(im, name, *flags):
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.ppm"
        im.save(src)
        subprocess.run(["cjpeg", *flags, "-outfile", str(OUT / name), str(src)], check=True)

def ycck(im, name, subsampling):
    tj = ctypes.CDLL("/opt/homebrew/lib/libturbojpeg.dylib")
    tj.tjInitCompress.restype = ctypes.c_void_p
    handle = tj.tjInitCompress()
    w, h = im.size
    data = im.tobytes()
    buf = ctypes.POINTER(ctypes.c_ubyte)()
    size = ctypes.c_ulong(0)
    tj.tjCompress2(ctypes.c_void_p(handle), data, w, 0, h, 11, ctypes.byref(buf), ctypes.byref(size), subsampling, 95, 0)
    (OUT / name).write_bytes(ctypes.string_at(buf, size.value))
    tj.tjFree(buf)
    tj.tjDestroy(ctypes.c_void_p(handle))

OUT.mkdir(exist_ok=True)
for w, h in [(1, 1), (7, 9), (37, 35), (64, 49)]:
    for sub, tag in [(0, "444"), (1, "422"), (2, "420")]:
        picture(w, h).save(OUT / f"b{tag}_{w}x{h}.jpg", quality=95, subsampling=sub)
        picture(w, h).save(OUT / f"p{tag}_{w}x{h}.jpg", quality=90, subsampling=sub, progressive=True)
    picture(w, h, "L").save(OUT / f"gray_{w}x{h}.jpg", quality=95)
    picture(w, h, "L").save(OUT / f"pgray_{w}x{h}.jpg", quality=80, progressive=True)
    picture(w, h, "CMYK").save(OUT / f"cmyk_{w}x{h}.jpg", quality=95)
for sub, tag in [(0, "444"), (2, "420")]:
    noise(37, 35).save(OUT / f"noise{tag}.jpg", quality=95, subsampling=sub)
    noise(37, 35).save(OUT / f"pnoise{tag}.jpg", quality=95, subsampling=sub, progressive=True)
    picture(83, 61).save(OUT / f"restart{tag}.jpg", quality=92, subsampling=sub, restart_marker_blocks=3)
    picture(83, 61).save(OUT / f"prestart{tag}.jpg", quality=92, subsampling=sub, progressive=True, restart_marker_blocks=2)
    picture(83, 61).save(OUT / f"q50_{tag}.jpg", quality=50, subsampling=sub)
    picture(83, 61).save(OUT / f"pq50_{tag}.jpg", quality=50, subsampling=sub, progressive=True)
    ycck(picture(35, 37, "CMYK"), f"ycck{tag}.jpg", sub)
cjpeg(picture(45, 29), "s411.jpg", "-sample", "4x1,1x1,1x1")
cjpeg(picture(45, 29), "s440.jpg", "-sample", "1x2,1x1,1x1")
cjpeg(picture(45, 29), "s32.jpg", "-sample", "3x2,1x1,1x1")
cjpeg(picture(45, 29), "s21_12.jpg", "-sample", "2x2,2x1,1x2")
cjpeg(picture(45, 29), "rgb.jpg", "-rgb")
cjpeg(picture(45, 29), "restart_rows.jpg", "-restart", "1", "-sample", "2x2,1x1,1x1")
cjpeg(picture(45, 29), "pscans.jpg", "-progressive", "-sample", "2x1,1x1,1x1")
# Large enough (over 65536 pixels) to decode on several threads: the pipelined
# baseline scan, restart intervals split across threads, and progressive.
big = picture(480, 360)
big.save(OUT / "mt_b420.jpg", quality=90, subsampling=2)
big.save(OUT / "mt_b444.jpg", quality=90, subsampling=0)
big.save(OUT / "mt_restart.jpg", quality=90, subsampling=2, restart_marker_blocks=4)
big.save(OUT / "mt_p420.jpg", quality=90, subsampling=2, progressive=True)
big.convert("L").save(OUT / "mt_gray.jpg", quality=90)
cjpeg(big, "mt_b422.jpg", "-sample", "2x1,1x1,1x1", "-quality", "90")
print(len(list(OUT.glob("*.jpg"))), "fixtures")
