from __future__ import annotations

import base64
import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from vassilflow.community.office.engine import office_engine
from vassilflow.community.office.errors import (
    OfficeOperationError,
    OfficeRevisionConflictError,
    OfficeTemplateConflictError,
    OfficeTemplateError,
    OfficeTemplateIntegrityError,
)
from vassilflow.community.office.instantiation import (
    OfficeTemplateInstantiationService,
    OfficeTemplatePictureBinding,
    OfficeTemplateTextBinding,
)
from vassilflow.community.office.models import PptxTextReplacement
from vassilflow.community.office.project_workflow import OfficeProjectWorkflowService
from vassilflow.community.office.render import OfficeRenderResult, RenderedOfficePage
from vassilflow.community.office.revisions import OfficeRevisionStore
from vassilflow.community.office.templates import (
    TEMPLATE_INSPECTION_SCHEMA,
    TEMPLATE_PREFLIGHT_SCHEMA,
    TEMPLATE_RENDER_EVIDENCE_SCHEMA,
    TEMPLATE_SCHEMA,
    TEMPLATE_VERSION_SCHEMA,
    OfficeTemplateSlotDraft,
    OfficeTemplateStore,
)

_TEMPLATE_ID = f"oft_{'1' * 32}"
_CREATED_AT = datetime(2026, 7, 17, 8, 30, tzinfo=UTC)
_PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
_REPLACEMENT_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAJCAYAAAA7KqwyAAAAAXNSR0IArs4c6QAAAARnQU1BAACxjwv8YQUAAAAJcEhZcwAADsMAAA7DAcdvqGQAAAAzSURBVChTY5D3q/xPCWYAEa8//SAKg9Q+ztaBY+oZQArGagC6Tcg2omOsBpCCh4EB6BgABGBPSggMnrAAAAAASUVORK5CYII="
)


def _pptx(*, external_relationship: bool = False, slide_count: int = 1) -> bytes:
    slide_overrides = "\n".join(f'  <Override PartName="/ppt/slides/slide{index}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>' for index in range(1, slide_count + 1))
    content_types = f"""<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="png" ContentType="image/png"/>
  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
{slide_overrides}
</Types>"""
    root_relationships = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
</Relationships>"""
    slide_ids = "".join(f'<p:sldId id="{255 + index}" r:id="rIdSlide{index}"/>' for index in range(1, slide_count + 1))
    presentation = f"""<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <p:sldIdLst>{slide_ids}</p:sldIdLst>
  <p:sldSz cx="12192000" cy="6858000"/>
</p:presentation>"""
    slide_relationship_records = "\n".join(f'  <Relationship Id="rIdSlide{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{index}.xml"/>' for index in range(1, slide_count + 1))
    presentation_relationships = f"""<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
{slide_relationship_records}
</Relationships>"""
    hyperlink = '<a:hlinkClick r:id="rIdExternal"/>' if external_relationship else ""
    slide = f"""<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <p:cSld><p:spTree>
    <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>
    <p:sp>
      <p:nvSpPr><p:cNvPr id="2" name="Quarter title">{hyperlink}</p:cNvPr><p:cNvSpPr/><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr>
      <p:spPr><a:xfrm><a:off x="100" y="100"/><a:ext cx="5000000" cy="800000"/></a:xfrm></p:spPr>
      <p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>Quarterly update</a:t></a:r></a:p></p:txBody>
    </p:sp>
    <p:pic>
      <p:nvPicPr><p:cNvPr id="3" name="Hero image" descr="Product image"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr>
      <p:blipFill><a:blip r:embed="rIdImage"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>
      <p:spPr><a:xfrm><a:off x="100" y="1000000"/><a:ext cx="4000000" cy="3000000"/></a:xfrm></p:spPr>
    </p:pic>
  </p:spTree></p:cSld>
</p:sld>"""
    external = '<Relationship Id="rIdExternal" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="https://example.test/image.png" TargetMode="External"/>' if external_relationship else ""
    slide_relationships = f"""<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rIdImage" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image1.png"/>
  {external}
</Relationships>"""

    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_relationships)
        archive.writestr("ppt/presentation.xml", presentation)
        archive.writestr("ppt/_rels/presentation.xml.rels", presentation_relationships)
        for index in range(1, slide_count + 1):
            archive.writestr(f"ppt/slides/slide{index}.xml", slide)
            archive.writestr(
                f"ppt/slides/_rels/slide{index}.xml.rels",
                slide_relationships,
            )
        archive.writestr("ppt/media/image1.png", _PNG)
    return output.getvalue()


def _store(tmp_path: Path) -> OfficeTemplateStore:
    return OfficeTemplateStore(
        tmp_path / "office",
        clock=lambda: _CREATED_AT,
        template_id_factory=lambda: _TEMPLATE_ID,
    )


def _render_result(source: bytes, **kwargs) -> OfficeRenderResult:
    assert kwargs == {
        "suffix": ".pptx",
        "start_page": 1,
        "max_pages": 1,
        "dpi": 120,
    }
    page = RenderedOfficePage(
        page=1,
        filename="page-001.png",
        width=1,
        height=1,
        sha256=hashlib.sha256(_PNG).hexdigest(),
        data=_PNG,
        source_slide=1,
    )
    return OfficeRenderResult(
        format="pptx",
        renderer="test-renderer",
        renderer_version="1.0",
        pdfium_version="5.11.0",
        source_sha256=hashlib.sha256(source).hexdigest(),
        pipeline_fingerprint="a" * 64,
        page_count=1,
        start_page=1,
        dpi=120,
        pages=(page,),
    )


def _render_store(tmp_path: Path) -> OfficeTemplateStore:
    return OfficeTemplateStore(
        tmp_path / "office",
        clock=lambda: _CREATED_AT,
        template_id_factory=lambda: _TEMPLATE_ID,
        render_id_factory=lambda: f"otr_{'2' * 32}",
        renderer=_render_result,
    )


def _published_store(tmp_path: Path) -> tuple[OfficeTemplateStore, bytes]:
    source = _pptx()
    store = _render_store(tmp_path)
    commit = store.import_pptx(
        source,
        filename="company-template.pptx",
        title="Quarterly company deck",
    )
    candidates = store.load_version(commit.template_id, 1)["slot_candidates"]
    text = next(candidate for candidate in candidates if candidate["type"] == "text")
    picture = next(candidate for candidate in candidates if candidate["type"] == "picture")
    store.update_draft_slots(
        commit.template_id,
        1,
        [
            OfficeTemplateSlotDraft(
                key="headline",
                label="Headline",
                type="text",
                candidate_id=text["candidate_id"],
                max_length=200,
            ),
            OfficeTemplateSlotDraft(
                key="hero_image",
                label="Hero image",
                type="picture",
                candidate_id=picture["candidate_id"],
                required=False,
            ),
        ],
    )
    render = store.render_draft(commit.template_id, 1)
    store.review_draft_render(
        commit.template_id,
        1,
        render.evidence_id,
        status="reviewed",
        reviewer="alice",
    )
    store.publish_draft(commit.template_id, 1)
    return store, source


def test_import_pptx_publishes_source_bound_draft_and_candidates(tmp_path: Path) -> None:
    source = _pptx()
    store = _store(tmp_path)

    commit = store.import_pptx(
        source,
        filename="company-template.pptx",
        title="Quarterly company deck",
    )

    assert commit.template_id == _TEMPLATE_ID
    assert commit.version == 1
    assert commit.slot_candidate_count == 2
    assert commit.as_metadata()["storage_scope"] == "trusted_user"
    template = store.load_template(_TEMPLATE_ID)
    assert template == {
        "schema": TEMPLATE_SCHEMA,
        "template_id": _TEMPLATE_ID,
        "title": "Quarterly company deck",
        "format": "pptx",
        "owner_scope": "user",
        "created_at": "2026-07-17T08:30:00Z",
        "updated_at": "2026-07-17T08:30:00Z",
        "latest_version": 1,
        "draft_version": 1,
        "published_versions": [],
        "archived": False,
    }
    version = store.load_version(_TEMPLATE_ID, 1)
    assert version["schema"] == TEMPLATE_VERSION_SCHEMA
    assert version["status"] == "draft"
    assert version["source"] == {
        "sha256": commit.source_sha256,
        "size_bytes": len(source),
    }
    assert version["locked_policy"] == {
        "mode": "all_except_slots",
        "fixed_slide_count": 1,
        "fixed_object_structure": True,
        "structure_fingerprint": commit.structure_fingerprint,
        "allowed_slot_types": ["text", "picture"],
    }
    assert [(item["type"], item["path"]) for item in version["slot_candidates"]] == [
        ("text", "/slide[1]/shape[@id=2]"),
        ("picture", "/slide[1]/picture[@id=3]"),
    ]
    source_record, persisted_source = store.read_source(_TEMPLATE_ID, 1)
    assert source_record["source"]["sha256"] == commit.source_sha256
    assert persisted_source == source
    inspection = store.read_inspection(_TEMPLATE_ID, 1)
    assert inspection["schema"] == TEMPLATE_INSPECTION_SCHEMA
    assert inspection["source_sha256"] == commit.source_sha256
    preflight_path = tmp_path / "office" / "templates" / _TEMPLATE_ID / "drafts" / "v000001" / "preflight.json"
    assert json.loads(preflight_path.read_text(encoding="utf-8"))["schema"] == TEMPLATE_PREFLIGHT_SCHEMA
    assert store.list_templates() == [template]


def test_update_draft_slots_resolves_server_candidates_and_preserves_source(tmp_path: Path) -> None:
    source = _pptx()
    store = _store(tmp_path)
    commit = store.import_pptx(source, filename="company-template.pptx")
    version = store.load_version(commit.template_id, 1)
    text_candidate, picture_candidate = version["slot_candidates"]

    updated = store.update_draft_slots(
        commit.template_id,
        1,
        [
            OfficeTemplateSlotDraft(
                key="quarter_title",
                label="Quarter title",
                type="text",
                candidate_id=text_candidate["candidate_id"],
                max_length=120,
            ),
            OfficeTemplateSlotDraft(
                key="hero_image",
                label="Hero image",
                type="picture",
                candidate_id=picture_candidate["candidate_id"],
                required=False,
            ),
        ],
    )

    text_slot, picture_slot = updated["slots"]
    assert text_slot["selector"] == {
        "path": "/slide[1]/shape[@id=2]",
        "expected_text": "Quarterly update",
    }
    assert text_slot["constraints"] == {"max_length": 120}
    assert text_slot["allowed_operations"] == ["replace_pptx_text"]
    assert picture_slot["selector"] == {
        "path": "/slide[1]/picture[@id=3]",
        "expected_name": "Hero image",
        "expected_source_sha256": picture_candidate["source"]["sha256"],
    }
    assert picture_slot["required"] is False
    assert picture_slot["constraints"]["preserve_geometry"] is True
    _version, persisted_source = store.read_source(commit.template_id, 1)
    assert persisted_source == source


def test_update_draft_slots_rejects_stale_duplicate_and_mismatched_candidates(tmp_path: Path) -> None:
    store = _store(tmp_path)
    commit = store.import_pptx(_pptx(), filename="company-template.pptx")
    candidate = store.load_version(commit.template_id, 1)["slot_candidates"][0]

    with pytest.raises(OfficeTemplateConflictError, match="stale or missing"):
        store.update_draft_slots(
            commit.template_id,
            1,
            [
                OfficeTemplateSlotDraft(
                    key="headline",
                    label="Headline",
                    type="text",
                    candidate_id=f"otc_{'0' * 32}",
                )
            ],
        )
    with pytest.raises(OfficeTemplateConflictError, match="does not match"):
        store.update_draft_slots(
            commit.template_id,
            1,
            [
                OfficeTemplateSlotDraft(
                    key="headline",
                    label="Headline",
                    type="picture",
                    candidate_id=candidate["candidate_id"],
                )
            ],
        )
    with pytest.raises(OfficeTemplateError, match="mapped only once"):
        store.update_draft_slots(
            commit.template_id,
            1,
            [
                OfficeTemplateSlotDraft(
                    key="headline",
                    label="Headline",
                    type="text",
                    candidate_id=candidate["candidate_id"],
                ),
                OfficeTemplateSlotDraft(
                    key="headline_copy",
                    label="Headline copy",
                    type="text",
                    candidate_id=candidate["candidate_id"],
                ),
            ],
        )


def test_template_store_rejects_blocked_sources_and_tampered_bytes(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(OfficeOperationError, match="external relationships"):
        store.import_pptx(
            _pptx(external_relationship=True),
            filename="unsafe-template.pptx",
        )

    commit = store.import_pptx(_pptx(), filename="company-template.pptx")
    source_path = tmp_path / "office" / "templates" / commit.template_id / "drafts" / "v000001" / "source.pptx"
    source_path.write_bytes(b"tampered")
    with pytest.raises(OfficeTemplateIntegrityError, match="SHA-256"):
        store.load_version(commit.template_id, 1)


def test_template_reads_do_not_create_ghosts_and_reject_tampered_slots(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(OfficeTemplateError, match="not found"):
        store.load_template(_TEMPLATE_ID)
    assert not (tmp_path / "office" / "templates" / _TEMPLATE_ID).exists()

    commit = store.import_pptx(_pptx(), filename="company-template.pptx")
    candidate = store.load_version(commit.template_id, 1)["slot_candidates"][0]
    store.update_draft_slots(
        commit.template_id,
        1,
        [
            OfficeTemplateSlotDraft(
                key="headline",
                label="Headline",
                type="text",
                candidate_id=candidate["candidate_id"],
            )
        ],
    )
    version_path = tmp_path / "office" / "templates" / commit.template_id / "drafts" / "v000001" / "version.json"
    payload = json.loads(version_path.read_text(encoding="utf-8"))
    payload["slots"][0]["allowed_operations"] = ["format_pptx_shapes"]
    version_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(OfficeTemplateIntegrityError, match="slot mapping"):
        store.load_version(commit.template_id, 1)


def test_render_review_and_publish_create_one_immutable_version_snapshot(tmp_path: Path) -> None:
    store = _render_store(tmp_path)
    commit = store.import_pptx(_pptx(), filename="company-template.pptx")
    text_candidate = store.load_version(commit.template_id, 1)["slot_candidates"][0]
    store.update_draft_slots(
        commit.template_id,
        1,
        [
            OfficeTemplateSlotDraft(
                key="headline",
                label="Headline",
                type="text",
                candidate_id=text_candidate["candidate_id"],
                max_length=200,
            )
        ],
    )

    with pytest.raises(OfficeTemplateConflictError, match="render evidence"):
        store.publish_draft(commit.template_id, 1)

    render = store.render_draft(commit.template_id, 1)
    assert render.as_metadata()["render_evidence"] == {
        "schema": TEMPLATE_RENDER_EVIDENCE_SCHEMA,
        "evidence_id": f"otr_{'2' * 32}",
        "source_sha256": commit.source_sha256,
        "page_count": 1,
        "rendered_page_count": 1,
        "pipeline_fingerprint": "a" * 64,
        "visual_review_status": "pending",
    }
    evidence = store.load_render_evidence(
        commit.template_id,
        1,
        render.evidence_id,
    )
    assert evidence["pages"][0]["source_slide"] == 1
    _evidence, preview, preview_bytes = store.read_render_preview_page(
        commit.template_id,
        1,
        render.evidence_id,
        1,
    )
    assert preview["sha256"] == hashlib.sha256(_PNG).hexdigest()
    assert preview_bytes == _PNG

    with pytest.raises(OfficeTemplateConflictError, match="visual review"):
        store.publish_draft(commit.template_id, 1)
    store.review_draft_render(
        commit.template_id,
        1,
        render.evidence_id,
        status="external_review_required",
        reviewer="alice",
        note="Check the customer logo.",
    )
    with pytest.raises(OfficeTemplateConflictError, match="visual review"):
        store.publish_draft(commit.template_id, 1)
    reviewed = store.review_draft_render(
        commit.template_id,
        1,
        render.evidence_id,
        status="reviewed",
        reviewer="alice",
    )
    assert reviewed["render"]["reviewed_by"] == "alice"
    assert reviewed["render"]["visual_review_status"] == "reviewed"

    published = store.publish_draft(commit.template_id, 1)
    assert published["status"] == "published"
    assert published["published_at"] == "2026-07-17T08:30:00Z"
    template = store.load_template(commit.template_id)
    assert template["draft_version"] is None
    assert template["published_versions"] == [1]
    published_dir = tmp_path / "office" / "templates" / commit.template_id / "versions" / "v000001"
    assert (published_dir / "source.pptx").read_bytes() == _pptx()
    assert (published_dir / "renders" / render.evidence_id / "pages" / "page-00001.png").read_bytes() == _PNG
    published_metadata_before = (published_dir / "version.json").read_bytes()
    assert store.publish_draft(commit.template_id, 1) == published
    assert (published_dir / "version.json").read_bytes() == published_metadata_before
    with pytest.raises(OfficeTemplateConflictError, match="editable draft"):
        store.update_draft_slots(commit.template_id, 1, [])
    with pytest.raises(OfficeTemplateConflictError, match="cannot be rendered again"):
        store.render_draft(commit.template_id, 1)


def test_template_render_rejects_tampered_preview_bytes(tmp_path: Path) -> None:
    store = _render_store(tmp_path)
    commit = store.import_pptx(_pptx(), filename="company-template.pptx")
    render = store.render_draft(commit.template_id, 1)
    preview_path = tmp_path / "office" / "templates" / commit.template_id / "drafts" / "v000001" / "renders" / render.evidence_id / "pages" / "page-00001.png"
    preview_path.write_bytes(b"tampered")

    with pytest.raises(OfficeTemplateIntegrityError, match="integrity"):
        store.load_version(commit.template_id, 1)


def test_template_render_batches_full_deck_without_losing_slide_identity(tmp_path: Path) -> None:
    calls: list[tuple[int, int]] = []

    def render_window(source: bytes, **kwargs) -> OfficeRenderResult:
        start_page = kwargs["start_page"]
        max_pages = kwargs["max_pages"]
        calls.append((start_page, max_pages))
        pages = tuple(
            RenderedOfficePage(
                page=page,
                filename=f"page-{page:03d}.png",
                width=1,
                height=1,
                sha256=hashlib.sha256(_PNG).hexdigest(),
                data=_PNG,
                source_slide=page,
            )
            for page in range(start_page, min(13, start_page + max_pages - 1) + 1)
        )
        return OfficeRenderResult(
            format="pptx",
            renderer="test-renderer",
            renderer_version="1.0",
            pdfium_version="5.11.0",
            source_sha256=hashlib.sha256(source).hexdigest(),
            pipeline_fingerprint="b" * 64,
            page_count=13,
            start_page=start_page,
            dpi=kwargs["dpi"],
            pages=pages,
        )

    store = OfficeTemplateStore(
        tmp_path / "office",
        clock=lambda: _CREATED_AT,
        template_id_factory=lambda: _TEMPLATE_ID,
        render_id_factory=lambda: f"otr_{'3' * 32}",
        renderer=render_window,
    )
    commit = store.import_pptx(
        _pptx(slide_count=13),
        filename="long-template.pptx",
    )

    render = store.render_draft(commit.template_id, 1)
    evidence = store.load_render_evidence(
        commit.template_id,
        1,
        render.evidence_id,
    )

    assert calls == [(1, 12), (13, 1)]
    assert render.page_count == 13
    assert render.rendered_page_count == 13
    assert [page["source_slide"] for page in evidence["pages"]] == list(range(1, 14))


def test_published_template_instantiation_commits_exact_baseline_policy_and_render(
    tmp_path: Path,
) -> None:
    template_store, source = _published_store(tmp_path)
    revision_ids = iter(
        [
            f"ofr_{'3' * 32}",
            f"ofr_{'4' * 32}",
        ]
    )
    revision_store = OfficeRevisionStore(
        tmp_path / "office",
        clock=lambda: _CREATED_AT,
        project_id_factory=lambda: f"ofp_{'5' * 32}",
        revision_id_factory=lambda: next(revision_ids),
        evidence_id_factory=lambda: f"ofe_{'6' * 32}",
    )
    service = OfficeTemplateInstantiationService(
        template_store,
        revision_store,
        renderer=_render_result,
    )

    instantiated = service.instantiate(
        _TEMPLATE_ID,
        1,
        title="Q4 customer update",
        bindings=[
            OfficeTemplateTextBinding(key="headline", value="Q4 customer update"),
            OfficeTemplatePictureBinding(
                key="hero_image",
                data=_REPLACEMENT_PNG,
                filename="hero.png",
                content_type="image/png",
            ),
        ],
    )

    assert instantiated.project_title == "Q4 customer update"
    assert instantiated.bound_slot_keys == ("headline", "hero_image")
    assert instantiated.omitted_optional_slot_keys == ()
    assert instantiated.render_evidence_status == "available"
    assert len(instantiated.render_evidence) == 1
    project = revision_store.load_project(instantiated.project.project_id)
    assert project["resource_versions"]["template"] == {
        "template_id": _TEMPLATE_ID,
        "version": 1,
        "source_sha256": hashlib.sha256(source).hexdigest(),
    }
    baseline, baseline_bytes = revision_store.read_revision_artifact(
        instantiated.project.project_id,
        instantiated.project.baseline_revision_id or "",
    )
    assert baseline_bytes == source
    assert baseline["resource_versions"] == project["resource_versions"]
    current, current_bytes = revision_store.read_revision_artifact(
        instantiated.project.project_id,
        instantiated.project.revision_id,
    )
    assert current_bytes != source
    assert current["resource_versions"] == project["resource_versions"]
    assert current["template_policy"]["requested_target_paths"] == [
        "/slide[1]/picture[@id=3]",
        "/slide[1]/shape[@id=2]",
    ]
    assert set(current["template_policy"]["changed_target_paths"]) <= set(current["template_policy"]["allowed_target_paths"])
    evidence = revision_store.list_render_evidence(
        instantiated.project.project_id,
        revision_id=instantiated.project.revision_id,
    )
    assert len(evidence) == 1
    assert evidence[0]["source"]["sha256"] == hashlib.sha256(current_bytes).hexdigest()


def test_template_instantiation_rejects_missing_unknown_and_out_of_slot_edits(
    tmp_path: Path,
) -> None:
    template_store, source = _published_store(tmp_path)
    revision_store = OfficeRevisionStore(tmp_path / "office")
    service = OfficeTemplateInstantiationService(template_store, revision_store)

    with pytest.raises(OfficeTemplateConflictError, match="required bindings"):
        service.instantiate(_TEMPLATE_ID, 1, bindings=[], render=False)
    with pytest.raises(OfficeTemplateConflictError, match="unknown or stale"):
        service.instantiate(
            _TEMPLATE_ID,
            1,
            bindings=[OfficeTemplateTextBinding(key="unknown", value="value")],
            render=False,
        )
    with pytest.raises(OfficeTemplateConflictError, match="unmapped"):
        template_store.enforce_published_edit_policy(
            _TEMPLATE_ID,
            1,
            source=source,
            result=source,
            operations=[
                PptxTextReplacement(
                    paths=["/slide[1]/shape[@id=99]"],
                    find="not present",
                    replace="blocked",
                )
            ],
            receipt={},
        )
    assert revision_store.list_projects() == []


def test_template_project_revision_cannot_bypass_policy_evidence(tmp_path: Path) -> None:
    template_store, _source = _published_store(tmp_path)
    revision_ids = iter(
        [
            f"ofr_{'7' * 32}",
            f"ofr_{'8' * 32}",
            f"ofr_{'9' * 32}",
        ]
    )
    revision_store = OfficeRevisionStore(
        tmp_path / "office",
        project_id_factory=lambda: f"ofp_{'a' * 32}",
        revision_id_factory=lambda: next(revision_ids),
    )
    instantiated = OfficeTemplateInstantiationService(
        template_store,
        revision_store,
    ).instantiate(
        _TEMPLATE_ID,
        1,
        bindings=[OfficeTemplateTextBinding(key="headline", value="First")],
        render=False,
    )
    _revision, current = revision_store.read_revision_artifact(
        instantiated.project.project_id,
        instantiated.project.revision_id,
    )
    operation = PptxTextReplacement(
        paths=["/slide[1]/shape[@id=2]"],
        find="First",
        replace="Second",
    )
    result, _reports, receipt = office_engine.edit_with_receipt(
        current,
        suffix=".pptx",
        operations=[operation],
    )

    with pytest.raises(OfficeRevisionConflictError, match="cannot be attached"):
        revision_store.commit_edit(
            source=current,
            result=result,
            suffix=".pptx",
            source_path="/mnt/user-data/outputs/first.pptx",
            output_path="/mnt/user-data/outputs/second.pptx",
            thread_id=None,
            receipt=receipt,
            source_validation=office_engine.validate(current, suffix=".pptx"),
            result_validation=office_engine.validate(result, suffix=".pptx"),
            project_id=instantiated.project.project_id,
            parent_revision_id=instantiated.project.revision_id,
        )


def test_template_project_restore_rechecks_every_published_slot_and_structure(
    tmp_path: Path,
) -> None:
    template_store, source = _published_store(tmp_path)
    revision_ids = iter(
        [
            f"ofr_{'b' * 32}",
            f"ofr_{'c' * 32}",
            f"ofr_{'d' * 32}",
        ]
    )
    revision_store = OfficeRevisionStore(
        tmp_path / "office",
        project_id_factory=lambda: f"ofp_{'e' * 32}",
        revision_id_factory=lambda: next(revision_ids),
    )
    instantiated = OfficeTemplateInstantiationService(
        template_store,
        revision_store,
    ).instantiate(
        _TEMPLATE_ID,
        1,
        bindings=[OfficeTemplateTextBinding(key="headline", value="Changed headline")],
        render=False,
    )

    restored = OfficeProjectWorkflowService(
        revision_store,
        template_store=template_store,
    ).restore_revision(
        instantiated.project.project_id,
        instantiated.project.baseline_revision_id or "",
        expected_current_revision_id=instantiated.project.revision_id,
    )

    revision, artifact = revision_store.read_revision_artifact(
        instantiated.project.project_id,
        restored.project.revision_id,
    )
    assert artifact == source
    assert revision["kind"] == "restore"
    assert revision["operation_receipt"]["semantic_changes"]["coverage"] == "complete"
    assert revision["template_policy"]["requested_target_paths"] == [
        "/slide[1]/picture[@id=3]",
        "/slide[1]/shape[@id=2]",
    ]
    assert revision["template_policy"]["changed_target_paths"] == [
        "/slide[1]/shape[@id=2]"
    ]
