# Native PPTX geometry corpus

This corpus gates VassilFlow's read-only PPTX geometry evidence against real
PowerPoint and WPS Presentation round trips. It is separate from the general
edit-surface and native-generation corpora.

The deterministic three-slide seed covers nested group scale, rotation and
flip transforms; a non-zero group child offset; grouped-picture effective PPI;
a frame fully outside the slide; and a picture frame materially clipped by the
slide boundary. Stable object names connect package inspection, preflight
findings, and native producer evidence without depending on array position.

Rebuild the deterministic seed from `backend/`:

```powershell
uv run python scripts/build_pptx_geometry_seed.py `
  --output-dir tests/fixtures/office/pptx/geometry `
  --overwrite
```

Recreate a native lane from the repository root with the named application
installed and closed:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts/office-pptx-native-roundtrip.ps1 `
  -Producer PowerPoint `
  -InputPath backend/tests/fixtures/office/pptx/geometry/seed-v1.pptx `
  -OutputPath backend/tests/fixtures/office/pptx/geometry/powerpoint-16-v1.pptx `
  -ReceiptPath backend/tests/fixtures/office/pptx/geometry/powerpoint-16-v1.receipt.json `
  -Overwrite
```

Use `-Producer WPS` and the `wps-v1` output and receipt names for the WPS lane.
After refreshing any fixture, update its manifest hashes and observed package
metadata, run the geometry corpus tests, then render and visually inspect all
three slides before accepting the refresh. The stored render hashes are
evidence from the recorded renderer pipeline, not a replacement for that
visual review.
