# luce-jpeg

A baseline and progressive JPEG decoder and a baseline encoder for Luce/Base.

Split out of luce-image on 2026-09-22 so every file format is its own package, like luce-svg and luce-psd. luce-image depends on it for `Image.open`/`save`; it depends on luce-raster.

## Decoding

```luce
import jpeg

let found = try jpeg.info(data)                     # width, height, components, progressive
let pixels = try alloc u8[found.width * found.height * 4]
try jpeg.decode_rgba8(data, pixels)                 # 8-bit RGBA, alpha 255, every processor
try jpeg.decode_rgb8(data, rgb, jpeg.Options(scale = 8))   # 1/8 size preview

# Bands of rows, top to bottom, on the calling thread:
try jpeg.decode_rows(data, sink, (void*)&state, layout = .rgba)

# The Raster route luce-image uses: f64 samples.
try jpeg.probe(&raster)
try raster.allocate()
try jpeg.decode(&raster)
```

- `Options.scale` is 1, 2, 4 or 8. A scaled decode comes straight from the DCT: each output pixel is the mean of the full-size pixels it covers, before rounding, which is what libjpeg's reduced IDCTs compute in fixed point. Sizes round up (`info.scaled_width(scale)`).
- `Options.threads` counts the caller's thread; 0 uses every processor.
- Every route gives the same samples, bit for bit those of the plain float decoder in luce-jpeg 0.1 (exact f64 IDCT, bilinear "fancy" upsampling, f64 YCbCr).

## How it is fast

Entropy decoding uses 11-bit Huffman lookahead with run, value and length for most AC coefficients in one lookup, and a 64-bit bit reader refilled several bytes at a time. Restart intervals decode on every processor. For a baseline picture in one interleaved scan, the calling thread entropy-decodes MCU rows while workers run the IDCT and colour conversion of finished rows, so rendering hides behind entropy decoding. The IDCT skips zero coefficients and rows (which only omits additions of zero); progressive refinement walks a bitmap of nonzero coefficients.

24 MP on an M4 Max (16 cores), `tests/bench.lucb`:

| Picture | 0.1 (Raster) | 0.2 `decode_rgba8` | 0.2 Raster |
| --- | ---: | ---: | ---: |
| baseline 4:2:0 q95 | 3650 ms | 91 ms | 117 ms |
| baseline 4:4:4 q90 | 5649 ms | 103 ms | |
| baseline 4:2:0 with restart markers | 4563 ms | 50 ms | |
| progressive 4:2:0 q95 | 4934 ms | 289 ms | |
| progressive 4:4:4 q90 | 5435 ms | 324 ms | |

## Tests

```
./test.sh    # the module's tests, then the drivers in native and C modes against tests/fixtures
```

`tests/fixtures/golden.txt` holds the 0.1 decoder's output for every fixture; `tests/make_fixtures.py` made the fixtures with Pillow, cjpeg and TurboJPEG. With Pillow installed the gate also compares full-size and scaled decodes with libjpeg's (within 4). `tests/bench.lucb` times a decode: `bench <file.jpg> [repeats] [raster|rgba|rgb|rows] [scale] [threads]`.
