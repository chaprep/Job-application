"""Versioned API/model contracts. Source IDs survive edits and are never printed."""
from datetime import date, datetime
from typing import Annotated, Literal
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator, field_validator
from .content import upgrade

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100000)]
Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
Identity = Annotated[str, StringConstraints(pattern=r'^[A-Za-z0-9_-]{1,64}$')]
Stage = Literal['applied','screening','interviewing','offer','accepted','rejected','withdrawn']


def identity():
    return 's_' + uuid4().hex


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid')


class LinkSpan(Model):
    start: int | None = Field(ge=0)
    end: int | None = Field(ge=0)
    url: str = Field(max_length=4000)
    source_link_id: Identity | None = None
    unresolved_label: str | None = Field(default=None, max_length=100000)


class ContactLink(Model):
    id: Identity = Field(default_factory=identity)
    label: str = Field(max_length=1000)
    url: str = Field(max_length=4000)
    source_link_id: Identity | None = None


class UnresolvedLink(ContactLink):
    label: str = Field(max_length=100000)
    reason: str = Field(max_length=1000)


class Claim(Model):
    id: Identity = Field(default_factory=identity)
    text: str = Field(min_length=1, max_length=100000)
    source_refs: list[Identity] = Field(default_factory=list, max_length=200)
    emphasis: list[str] = Field(default_factory=list, max_length=10)
    links: list[LinkSpan] = Field(default_factory=list, max_length=100)


class Contact(Model):
    name: str = Field(default='', max_length=200)
    email: str = Field(default='', max_length=320)
    phone: str = Field(default='', max_length=100)
    location: str = Field(default='', max_length=300)
    links: list[ContactLink] = Field(default_factory=list, max_length=20)

    @model_validator(mode='before')
    @classmethod
    def legacy_links(cls, value):
        if isinstance(value, dict):
            return upgrade({'schema_version': '1', 'contact': value})['contact']
        return value


class Entry(Model):
    id: Identity = Field(default_factory=identity)
    title: str = Field(default='', max_length=500)
    organization: str = Field(default='', max_length=500)
    location: str = Field(default='', max_length=300)
    dates: str = Field(default='', max_length=200)
    link: str = Field(default='', max_length=2000)
    link_label: str = Field(default='', max_length=1000)
    link_source_id: Identity | None = None
    title_links: list[LinkSpan] = Field(default_factory=list, max_length=30)
    organization_links: list[LinkSpan] = Field(default_factory=list, max_length=30)
    description: list[Claim] = Field(default_factory=list, max_length=30)
    bullets: list[Claim] = Field(default_factory=list, max_length=50)
    children: list['Entry'] = Field(default_factory=list, max_length=30)


class SkillGroup(Model):
    id: Identity = Field(default_factory=identity)
    label: str = Field(default='', max_length=200)
    items: list[Claim] = Field(default_factory=list, max_length=100)


class ExtraSection(Model):
    title: Short
    entries: list[Entry] = Field(default_factory=list, max_length=50)


class VersionedContent(Model):
    schema_version: Literal['2'] = '2'
    unresolved_links: list[UnresolvedLink] = Field(default_factory=list, max_length=300)

    @model_validator(mode='before')
    @classmethod
    def legacy_content(cls, value):
        return upgrade(value)


class ResumeContent(VersionedContent):
    contact: Contact
    summary: list[Claim] = Field(default_factory=list, max_length=10)
    skills: list[SkillGroup] = Field(default_factory=list, max_length=20)
    experience: list[Entry] = Field(default_factory=list, max_length=50)
    projects: list[Entry] = Field(default_factory=list, max_length=50)
    education: list[Entry] = Field(default_factory=list, max_length=30)
    additional_sections: list[ExtraSection] = Field(default_factory=list, max_length=30)


class Finding(Model):
    field: str
    severity: Literal['warning','error']
    category: Literal['structure','grounding','relevance','style','consistency','coverage','pdf']
    explanation: Text
    source_refs: list[str] = Field(default_factory=list)
    suggested_replacement: str | None = None


class OrganisedResume(Model):
    content: ResumeContent
    findings: list[Finding] = Field(default_factory=list)


class Requirements(Model):
    responsibilities: list[str] = Field(default_factory=list)
    required: list[str] = Field(default_factory=list)
    preferred: list[str] = Field(default_factory=list)


class JobFields(Model):
    company: str | None = None
    title: str | None = None
    location: str | None = None
    expected_salary: str | None = None
    advertised_salary: str | None = None
    employment_type: str | None = None
    application_deadline: str | None = None
    recruiter_details: str | None = None
    job_reference: str | None = None
    tailoring_instructions: str | None = None
    source_url: str | None = None
    jd_text: str | None = None
    requirements: Requirements | None = None


class JobInput(Model):
    source_type: Literal['url','pasted']
    source_url: str | None = Field(default=None, max_length=4000)
    jd_text: str | None = None

    @model_validator(mode='after')
    def source_present(self):
        if self.source_type == 'url' and not (self.source_url or '').strip():
            raise ValueError('A job URL is required')
        if self.source_type == 'pasted' and not (self.jd_text or '').strip():
            raise ValueError('Full JD text is required')
        return self


class ExtractedJob(Model):
    jd_text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] | None
    company: str | None = None
    title: str | None = None
    location: str | None = None
    advertised_salary: str | None = None
    employment_type: str | None = None
    application_deadline: str | None = None
    recruiter_details: str | None = None
    job_reference: str | None = None
    requirements: Requirements = Field(default_factory=Requirements)
    evidence: dict[str, str] = Field(default_factory=dict)
    findings: list[Finding] = Field(default_factory=list)


class CoverLetter(VersionedContent):
    contact: Contact
    letter_date: Annotated[str, StringConstraints(pattern=r'^\d{4}-\d{2}-\d{2}$')] | None = None
    salutation: Short
    paragraphs: list[Claim] = Field(min_length=1, max_length=8)
    closing: Short = 'Kind regards,'
    signature: Short

    @field_validator('letter_date')
    @classmethod
    def valid_letter_date(cls, value):
        if value is not None:
            date.fromisoformat(value)
        return value


class Review(Model):
    findings: list[Finding]


class ResumeDraft(Model):
    content: ResumeContent


class LetterDraft(Model):
    content: CoverLetter


class ResumeRevision(ResumeDraft):
    changes: list[str]


class LetterRevision(LetterDraft):
    changes: list[str]


class ResumeSave(Model):
    content: ResumeContent


class Activate(ResumeSave):
    confirmed: Literal[True]
    override_invalid_links: bool = False


class Instructions(Model):
    instructions: str | None = Field(default=None, max_length=10000)


class RevisionRequest(Model):
    instructions: Text


class DocumentSelection(Model):
    document_id: int = Field(gt=0)


class DocumentSave(Model):
    content: ResumeContent | CoverLetter


class ApplicationInput(Model):
    origin: Literal['jab','external']
    company: Short
    role: Short
    job_id: int | None = Field(default=None, gt=0)
    applied_on: date | None = None
    resume_document_id: int | None = Field(default=None, gt=0)
    cover_letter_document_id: int | None = Field(default=None, gt=0)
    application_url: str | None = None
    stage: Stage = 'applied'


class StageChange(Model):
    stage: Stage
    occurred_at: datetime | None = None


class Note(Model):
    note: Text
    occurred_at: datetime | None = None


class FollowUp(Model):
    next_action: str | None = Field(default=None, max_length=10000)
    due_on: date | None = None


class Correction(Model):
    reason: Text
    company: Short | None = None
    role: Short | None = None
    application_url: str | None = None
    applied_on: date | None = None
    resume_document_id: int | None = Field(default=None, gt=0)
    cover_letter_document_id: int | None = Field(default=None, gt=0)


class TaskAccepted(Model):
    task_id: int
    resume_version_id: int | None = None
    job_id: int | None = None
    run_id: int | None = None
    document_id: int | None = None


class TaskRecord(Model):
    id: int
    action: str
    resume_version_id: int | None
    job_id: int | None
    run_id: int | None
    document_id: int | None
    input: dict
    status: Literal['queued','running','succeeded','failed','interrupted']
    step: str
    result: dict | None
    error_code: str | None
    error_message: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None


class Page(Model):
    items: list[dict]
    total: int
    limit: int
    offset: int
