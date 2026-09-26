# luce-jpeg

A fast multithreaded baseline and progressive JPEG decoder and baseline encoder for Luce/Base.

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
# The same with the file read in pieces: read(context, offset, buffer) gives its bytes.
try jpeg.decode_rows_at(read, (void*)&file, size, sink, (void*)&state)

# The Raster route luce-image uses: f64 samples.
try jpeg.probe(&raster)
try raster.allocate()
try jpeg.decode(&raster)
```

- `Options.scale` is 1, 2, 4 or 8. A scaled decode comes straight from the DCT: each output pixel is the mean of the full-size pixels it covers, before rounding, which is what libjpeg's reduced IDCTs compute in fixed point. Sizes round up (`info.scaled_width(scale)`).
- `Options.threads` counts the caller's thread; 0 uses every processor.
- A progressive picture decoding to rows can show itself early: `Options.coarse` hears, once its first scans give every component its DC coefficients, the picture at 1/8 size as RGBA (straight from the DC, as a 1/8 decode is), long before any row. Its rows then render from the coefficients a group of MCU rows at a time through a ring of planes, so a row decode holds the coefficients (two bytes each) and a few rows, not a plane for every sample too.
- `decode_rows_at` holds a megabyte window of the file, sliding on before each marker segment and, in a scan, between MCUs; restart intervals then decode on one thread.
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

## Encoding

```luce
var out = Buffer()
try jpeg.encode_rgba8(pixels, width, height, &out)            # q90 4:2:0, every processor
try jpeg.encode_rgb8(rgb, width, height, &out, jpeg.EncodeOptions(quality = 95, subsampling = .s444, optimize = true))

# In bands, for pictures too big to hold as 8-bit pixels:
var encoder = try jpeg.Encoder.begin(width, height, .rgba, &out, jpeg.EncodeOptions(restart = true))
defer encoder.close()
try encoder.write_rows(band, rows)                            # as often as needed, any row count
try encoder.finish()

try jpeg.encode(&raster, &out, quality = 90)                  # a Raster, 4:4:4 as before
```

- `EncodeOptions`: `quality` 1..100 (Annex K tables scaled as IJG does), `subsampling` `.s444`/`.s422`/`.s420` (default 4:2:0; ignored for gray), `restart` (a marker after every MCU row, so decoders can split entropy decoding: this one decodes such a file a third faster), `optimize` (Huffman tables fitted in a second pass, about 3% smaller; keeps every block until `finish`), `threads`.
- An `Encoder` holds a few MCU rows a thread; rows come straight from the caller's buffer when whole groups arrive. Every route, thread count and push size gives the same bytes.
- Colour conversion, downsampling, the quantized AAN forward DCT and Huffman coding of each MCU row run on every processor into separate bit streams; the calling thread joins them with byte stuffing and the rows' first MCUs.

24 MP from an M4 Max, `tests/encode.lucb` (PSNR against the source):

| Encoding | Time, 16 cores | 1 thread | Size | PSNR |
| --- | ---: | ---: | ---: | ---: |
| 0.2 `encode` q90 (4:4:4, luma table for all) | 5682 ms | 5682 ms | 20.4 MB | 40.8 dB |
| q90 4:4:4 | 72 ms | | 10.4 MB | 40.0 dB |
| q90 4:2:2 | 62 ms | | 9.1 MB | 38.7 dB |
| q90 4:2:0 | 52 ms | 361 ms | 8.25 MB | 36.9 dB |
| q90 4:2:0 optimized | 63 ms | 460 ms | 8.03 MB | 36.9 dB |
| libjpeg-turbo (Pillow) q90 4:2:0 | 90 ms (1 thread) | | 8.33 MB | 37.0 dB |

## Tests

```
./test.sh    # the module's tests, then the drivers in native and C modes against tests/fixtures
```

`tests/fixtures/golden.txt` holds the 0.1 decoder's output for every fixture; `tests/make_fixtures.py` made the fixtures with Pillow, cjpeg and TurboJPEG. With Pillow installed the gate also compares full-size and scaled decodes with libjpeg's (within 4). `tests/bench.lucb` times a decode: `bench <file.jpg> [repeats] [raster|rgba|rgb|rows] [scale] [threads]`; `tests/encode.lucb` times encoding a decoded picture: `encode <in.jpg> <out.jpg> [repeats] [raster|rgba|rgb|gray|stream] [quality] [444|422|420] [r|o|ro|-] [threads]`. The gate also checks that encodings are identical across threads and streaming and as close to the source as libjpeg's.
