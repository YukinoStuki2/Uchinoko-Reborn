# Public source adjustments

The hashes in `release-source.json` describe the original 2.13.0 distribution
source, before the changes in this fork.

During the public migration, `app_py/tests/test_inquiry_dev1011_generic_pii.py`
was adjusted to generate an intentionally unusable, all-zero test-mode secret
sentinel inside its redaction test. The imported distribution had a
credential-shaped example literal that GitHub secret scanning rejected.
The test still asserts redaction and preservation of surrounding log text.
The rejected literal is not included in this fork's new commit history.
No service credential is required by this test; no security rule was disabled.

Other changes, including the FBX/dynamics fixes, project identity, and publicly
redistributable synthetic PhysBone fixtures, are recorded in the fork commits
and `repair/REBORN_SOURCE_VALIDATION.md`.
