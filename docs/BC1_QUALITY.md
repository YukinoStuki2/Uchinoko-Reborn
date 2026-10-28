# BC1 color fitting

The converter still emits the same BC1/DXT1 or BC3/DXT5 formats and mip counts.
Each BC1 4×4 block takes eight bytes. Color fitting happens during conversion;
it does not add shader operations, materials, or texture memory in the game.

The previous encoder independently selected the minimum and maximum of each
RGB channel. For negatively correlated channels this can choose endpoints
that are absent from the source, flattening colored edges toward grey.

The quality encoder keeps the original range-fit as a fallback, then tries
principal-axis endpoints and two rounds of least-squares endpoint fitting.
Every candidate is quantized to RGB565 and scored using the decoded palette.
A candidate replaces the fallback only on strictly lower RGB squared error.
Equal-error candidates retain the original bytes. Working arrays are limited
to 8,192 blocks at a time.

The subsequent quantized refinement retains that fitted result as another
fallback. Pure colors and low-contrast blocks also try endpoints whose BC1
interpolants represent colors between RGB565 grid points. This avoids forcing
a constant color onto a coarse endpoint when an interpolant represents it
more accurately. Fixed palette assignments then permit a small independent
grid search per channel, followed by reassignment and exact decoded scoring.
Only lower-error candidates are accepted. Pure-color blocks remain uniform;
there is no dithering. BC3 alpha bytes are unchanged.

This does not recover detail removed by atlas downsampling. Better atlas
allocation and resampling are separate improvements.

## Verification

`tests/repair/test_bc1_quality.py` uses generated images and an independent
legacy encoder to check error bounds, gradients, solid blocks, padding,
chunk boundaries and unchanged BC3 alpha. The fitter accepts a candidate
only after decoding it and measuring lower squared RGB error. Private
model textures and local benchmark reports are not included.

Run `python -m pytest tests/repair/test_bc1_quality.py -q`. This verifies
compression properties, not equivalent perceived sharpness or gameplay FPS.
