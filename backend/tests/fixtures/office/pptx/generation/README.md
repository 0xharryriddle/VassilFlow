# Native PPTX generation corpus

This corpus gates VassilFlow's semantic PPTX compiler against real native
producer round trips. It is independent from the broader PPTX edit-surface
corpus in the adjacent `roundtrip` directory.

The deterministic seed covers all five generation layouts, native title
placeholders, text boxes, bullet paragraphs, simple shapes, embedded PNG
pictures, `cover` and `contain` fitting, accessible picture descriptions, and
stable `VFGEN:<slide-id>:<element-id>` authored names. The stored intent,
source image, generation receipt, and complete preflight are hash-bound in
`manifest.json`.

Rebuild deterministic artifacts from `backend/`:

```powershell
uv run python scripts/build_pptx_generation_seed.py `
  --output-dir tests/fixtures/office/pptx/generation `
  --overwrite
```

Recreate one native lane from the repository root with the named application
installed and closed:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts/office-pptx-native-roundtrip.ps1 `
  -Producer PowerPoint `
  -InputPath backend/tests/fixtures/office/pptx/generation/seed-v1.pptx `
  -OutputPath backend/tests/fixtures/office/pptx/generation/powerpoint-16-v1.pptx `
  -ReceiptPath backend/tests/fixtures/office/pptx/generation/powerpoint-16-v1.receipt.json `
  -Overwrite
```

Use `-Producer WPS` and the `wps-v1` output and receipt names for the WPS lane.
After refreshing a native fixture, update only its recorded hash and observed
package metadata, run the corpus tests, then render and visually inspect all
five seed slides before accepting the refresh.
