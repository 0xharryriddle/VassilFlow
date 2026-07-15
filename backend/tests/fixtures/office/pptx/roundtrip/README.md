# PPTX Native Round-Trip Corpus

This corpus gates the PPTX write surface and every later expansion. The seed
exercises mixed runs, paragraph alignment and spacing, direct shape style,
text-box margins, vertical anchoring, multiscript text, and an authored
connector with compound/alignment and independently sized line ends. Verified
fixtures also include linear and radial gradients plus an unadjusted preset
geometry shape, direct RGB pattern fill, and embedded PNG plus baseline JPEG
shape fills with stretch/crop, explicit tile framing, and canonical centered
framing. Slides 8-12 add direct solid and linear-gradient backgrounds plus
stretched JPEG, explicit tiled PNG, and 100-percent center-aligned PNG
backgrounds. Slide 13 adds three native picture objects: two share one PNG and
one owns a baseline JPEG. Their contract covers crop, stretch fill rectangle,
DPI where producer-stable, compression state, direct alpha/luminance/grayscale
effects, geometry, alt text, and source SHA-256. The corpus has 13 slides and
32 objects. Tests run typed run/paragraph/shape/line/background formatting,
source-only picture replacement, direct preset line-style, geometry, pattern,
and embedded PNG/baseline-JPEG writes, same-font metadata preservation,
relationship/media-part growth, framing no-ops, stale-source rejection, and
touched-part isolation. The same fixtures gate the read-only media cleanup
planner: native baselines must have no candidates, source-only replacement must
identify only the now-unreferenced exclusive JPEG, and the shared PNG must
remain live. The planner also verifies package-wide XML relationship integrity
and root reachability: all nine baseline images are reachable, while only the
exclusive old JPEG becomes unreachable after zero-reference image edges are
filtered. Any root-unreachable media island is reported only as bounded,
hash-bound diagnostic evidence with its incoming owner state. Centered framing
is a native center-aligned tile and may repeat when an asset is smaller than its
bounds.

Native picture objects intentionally use stretch framing. PowerPoint and WPS
preserve picture tile/center attributes but render them differently, so those
picture framing writes remain outside this corpus and the public write surface.

`manifest.json` is authoritative. A producer lane is `verified` only when its
fixture was opened and saved by the named native application, its receipt
matches the fixture hashes and package metadata, and the semantic contract
passes. Missing producers remain `pending`; the harness never substitutes
LibreOffice or another producer.

## Rebuild the seed

From `backend/`:

```powershell
uv run python scripts/build_pptx_roundtrip_seed.py `
  --output tests/fixtures/office/pptx/roundtrip/seed-v1.pptx `
  --overwrite
```

The generated SHA-256 must match `manifest.json` before creating native
fixtures.

## Create native fixtures

From the repository root on a Windows host with the target application
installed:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts/office-pptx-native-roundtrip.ps1 `
  -Producer PowerPoint `
  -InputPath backend/tests/fixtures/office/pptx/roundtrip/seed-v1.pptx `
  -OutputPath backend/tests/fixtures/office/pptx/roundtrip/powerpoint-16-v1.pptx `
  -ReceiptPath backend/tests/fixtures/office/pptx/roundtrip/powerpoint-16-v1.receipt.json `
  -Overwrite
```

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts/office-pptx-native-roundtrip.ps1 `
  -Producer WPS `
  -InputPath backend/tests/fixtures/office/pptx/roundtrip/seed-v1.pptx `
  -OutputPath backend/tests/fixtures/office/pptx/roundtrip/wps-v1.pptx `
  -ReceiptPath backend/tests/fixtures/office/pptx/roundtrip/wps-v1.receipt.json `
  -Overwrite
```

The WPS lane uses the
[documented `kwpp.application` presentation object](https://open.wps.cn/documents/app-integration-dev/wps365/client/wpsoffice/jsapi/macro-editor-api/function/createobject).
If WPS owns the shared PowerPoint COM registration, the PowerPoint lane starts
an installed `POWERPNT.EXE` automation process directly. Close any open
PowerPoint process first; the harness will not attach to it or change COM
registration.
The process-scoped execution-policy override does not change the host policy.

After reviewing the receipt and application metadata, update only that lane in
`manifest.json`, then run:

```powershell
uv run pytest -q tests/test_office_pptx_roundtrip_corpus.py
```

Do not mark `formatting_readiness.ready` true until every required producer is
verified and the edited file has also survived native reopen plus visual QA.
