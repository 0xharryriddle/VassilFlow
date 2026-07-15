# Third-Party Notices

## OfficeCLI

Portions of the run-aware DOCX replacement, typed selector, and OOXML
formatting designs in
`backend/packages/harness/vassilflow/community/office/docx.py` and
`backend/packages/harness/vassilflow/community/office/xlsx.py`, plus the
slide-order and read-only inspection rules in
`backend/packages/harness/vassilflow/community/office/pptx.py`, are adapted
from the OfficeCLI Word, Excel, and PowerPoint handlers.

- Source: https://github.com/iOfficeAI/OfficeCLI
- Reference commit: `b8669389dbe1f8a5fd0927a51b5ccf91b1dfe3e6`
- Copyright 2026 OfficeCLI (https://OfficeCLI.AI)
- License: Apache License 2.0

The applicable license and upstream NOTICE are reproduced beside the packaged
implementation as `LICENSE.officecli` and `NOTICE.officecli`.

## Office renderer image

The optional `docker/office-renderer` image installs these runtime components
without copying their source into the VassilFlow package:

- LibreOffice Writer: https://www.libreoffice.org/about-us/licenses/
- LibreOffice Calc: https://www.libreoffice.org/about-us/licenses/
- LibreOffice Impress: https://www.libreoffice.org/about-us/licenses/
- pypdfium2 and PDFium: https://github.com/pypdfium2-team/pypdfium2
- Pillow: https://python-pillow.github.io/

Their package license files remain in the built image under the locations
provided by Debian and the Python distributions. VassilFlow communicates with
the renderer as a separate service over HTTP.
