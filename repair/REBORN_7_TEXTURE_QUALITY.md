# Reborn.7 texture quality

Full conversion defaults to deterministic rectangular 4096² atlas packing, linear-light area downsampling and padded regions. The affine UV bake is retained; old explicit `atlas_layout=legacy-grid` jobs remain supported. Fast repack does not rebuild existing UVs.

BC1 now evaluates a principal-axis/least-squares candidate against the old encoder after actual RGB565 quantization, selecting the lower-error result per complete block. Format, texture bytes and material count remain unchanged. Conversion takes longer; do not promise higher runtime FPS.

Regression checks cover atlas allocation, BC1 error bounds, mip sizes and
byte-level cooked texture consistency using generated images. Private
textures and local measurements are not distributed. In-game viewing
distance and streaming behavior require separate validation.
