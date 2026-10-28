# Texture fidelity at the existing GPU budget

Reborn.10 improves opaque albedo preparation without changing atlas allocation,
UV transforms, texture dimensions, BC formats, mip counts, streaming flags or
material count. This is offline conversion work, not a new runtime effect.

- Moderate downsampling uses a two-lobe reconstruction filter in linear light,
  clamped to the local source color range to limit ringing. Deep minification
  retains area integration. Sources containing near-transparent pixels also
  retain area integration because their extended colors are inferred padding.
- The BC encoder evaluates more quantized endpoint candidates against the
  existing fitter. It accepts only a strictly lower decoded RGB error. BC3
  alpha encoding is unchanged. See [BC1 measurements](BC1_QUALITY.md).
- Opaque albedo mip levels average decoded sRGB light values, retaining float
  intermediate values until each output level is encoded. The general-purpose
  mip API remains unchanged for data maps and transparent UI textures.

A 4096-square BC1 atlas with a full mip chain remains 13 mips and
11,184,824 bytes. Validate visual differences at normal game distances;
compression error reduction is not equivalent to perceived sharpness.

Original texture resolution still limits detail. A 256-square source remains
256-square in its atlas region; improved encoding cannot invent real fine
features. Normal maps, masks and UI portraits are not reinterpreted as albedo.

Builds take longer. Texture allocation is checked from cooked package bytes;
whole-game memory residency and visual appearance still require an in-game
comparison on the target hardware.
