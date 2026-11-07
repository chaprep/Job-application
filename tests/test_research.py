"""Research transport, bounded model conversations, and workflow provenance."""
from dataclasses import replace
import json
from pathlib import Path
import socket
import sys
from unittest.mock import patch

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import database as d, repository as r, schemas as s
from backend.ai import AI
from backend.app import create_app
from backend.config import Settings
from backend.errors import BackendError
from backend.research import Research, read_page, search_web, research_history
from backend.service import Service
from backend_fixtures import resume_content, letter


@pytest.fixture
def settings(tmp_path):
    return Settings(database=tmp_path / 'jab.sqlite3', model='model', api_key='model-secret', zyte_api_key='zyte-secret')


@pytest.fixture(autouse=True)
def dns():
    def resolve(host, port, **kwargs):
        address = '127.0.0.1' if host in ('private.example', '127.0.0.1') else '93.184.216.34'
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, port))]
    with patch('backend.fetching.socket.getaddrinfo', side_effect=resolve):
        yield


@pytest.fixture
def setup_run(settings):
    db = d.connect(settings.database)
    d.migrate(db)
    source = resume_content().model_dump()
    resume = r.upload_resume(db, 'base.pdf', b'%PDF-1.7\nfixture\n%%EOF')
    r.start_extraction(db, resume)
    r.finish_extraction(db, resume, 'Candidate facts', source)
    d.activate_resume(db, resume, source)
    job = r.create_job(db, source_type='pasted', jd_text='Build Python services')
    r.save_job(db, job, company='Example', title='Engineer', confirm=True)
    run = r.create_run(db, job_id=job)
    r.start_run(db, run)
    inputs = {'kind': 'cover_letter', 'resume': source, 'job': r.get(db, 'jobs', job), 'current_date': '2026-11-07'}
    content = letter(source).model_dump()
    content['letter_date'] = inputs['current_date']
    yield db, run, inputs, {'content': content}
    db.close()


def zyte_response(request):
    if request.url.path.endswith('/search'):
        return httpx.Response(200, json={'status': 'success', 'fetchedAt': '2026-11-07T00:00:00Z',
            'organicResults': [{'rank': 1, 'title': 'Example platform', 'url': 'https://example.com/product', 'snippet': 'Reliable developer tools'}]})
    return httpx.Response(200, json={'url': json.loads(request.content)['url'], 'statusCode': 200,
        'browserHtml': '<html><title>Example platform</title><nav>Skip this</nav><main><h1>Developer tools</h1><p>Tools for reliable services.</p><a href="/engineering">Engineering</a></main></html>'})


def tool(name, arguments, identity='call_1'):
    return {'id': identity, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(arguments)}}


def envelope(content=None, tools=None):
    return httpx.Response(200, json={'choices': [{'message': {'role': 'assistant', 'content': content,
        **({'tool_calls': tools, 'reasoning_details': [{'type': 'reasoning.text', 'text': 'Inspect sources'}]} if tools else {})}}], 'usage': {'completion_tokens': 1}})


def test_search_and_reader_contracts(settings):
    requests = []
    def respond(request):
        requests.append(request)
        return zyte_response(request)
    transport = httpx.MockTransport(respond)
    found = search_web('Example developer platform', settings, 10, transport)
    assert found['results'][0]['url'] == 'https://example.com/product'
    assert json.loads(requests[0].content) == {'domain': 'google.com', 'query': 'Example developer platform', 'include': ['organic'], 'maxResults': 10}
    page = read_page(found['results'][0]['url'], settings, 10, transport)
    assert page['title'] == 'Example platform'
    assert 'Skip this' not in page['text']
    assert page['links'] == [{'text': 'Engineering', 'url': 'https://example.com/engineering'}]
    assert page['fetched_at'] and not page['truncated']


def test_page_truncation_and_redirect_validation(settings):
    def large(request):
        return httpx.Response(200, json={'url': 'https://example.com/final', 'statusCode': 200,
            'browserHtml': '<main>' + 'a' * 21000 + ''.join(f'<a href="/{i}">{i}</a>' for i in range(40)) + '</main>'})
    page = read_page('https://example.com', settings, 10, httpx.MockTransport(large))
    assert len(page['text']) == 20000 and page['truncated']
    assert len(page['links']) == 30 and page['url'].endswith('/final')
    def private(request):
        return httpx.Response(200, json={'url': 'http://private.example/', 'statusCode': 200, 'browserHtml': '<p>Blocked</p>'})
    with pytest.raises(BackendError, match='public HTTP'):
        read_page('https://example.com', settings, 10, httpx.MockTransport(private))


@pytest.mark.parametrize('payload', [{}, [], {'status': 'success', 'organicResults': []},
    {'status': 'success', 'fetchedAt': 'now', 'organicResults': [{'url': 2}]}])
def test_bad_search_responses(settings, payload):
    with pytest.raises(BackendError) as caught:
        search_web('Example', settings, 10, httpx.MockTransport(lambda request: httpx.Response(200, json=payload)))
    assert caught.value.code == 'zyte_invalid_response'


def test_empty_search_is_usable(settings):
    result = search_web('Example', settings, 10, httpx.MockTransport(lambda request: httpx.Response(200,
        json={'status': 'success', 'fetchedAt': 'now', 'organicResults': []})))
    assert result['results'] == []


@pytest.mark.parametrize('status', [400, 401, 403, 429, 500])
def test_failed_requests_are_counted_cached_and_sanitized(settings, status):
    requests = []
    def failed(request):
        requests.append(request)
        return httpx.Response(status, text='zyte-secret model-secret')
    research = Research(settings, transport=httpx.MockTransport(failed))
    first = research.execute(tool('search_web', {'query': 'Example'})['function'])
    second = research.execute(tool('search_web', {'query': 'Example'})['function'])
    assert 'error' in first and second['cached']
    assert research.searches == len(requests) == 1
    assert 'secret' not in json.dumps(first)


def test_arguments_limits_privacy_and_deadline(settings):
    requests, clock = [], [0]
    def respond(request):
        requests.append(request)
        return zyte_response(request)
    research = Research(replace(settings, research_max_searches=1, research_max_pages=1),
        transport=httpx.MockTransport(respond), clock=lambda: clock[0], private_terms=['Candidate Name'])
    for function in ({'name': 'search_web', 'arguments': '{'},
                     {'name': [], 'arguments': '{}'},
                     tool('search_web', {'query': 'Example', 'extra': True})['function'],
                     tool('search_web', {'query': 'Candidate Name Example'})['function'],
                     tool('search_web', {'query': 'person@example.com'})['function'],
                     tool('read_page', {'url': 'http://127.0.0.1/'})['function'],
                     tool('shell', {'command': 'anything'})['function']):
        assert 'error' in research.execute(function)
    assert not requests
    assert 'results' in research.execute(tool('search_web', {'query': 'Example'})['function'])
    assert research.execute(tool('search_web', {'query': 'Different'})['function'])['error']['code'] == 'search_limit'
    assert 'text' in research.execute(tool('read_page', {'url': 'https://example.com'})['function'])
    assert not research.active() and research.reason == 'request_limit'
    other = Research(settings, clock=lambda: clock[0])
    clock[0] = 301
    assert other.execute(tool('search_web', {'query': 'Example'})['function'])['error']['code'] == 'time_limit'


def test_adaptive_conversation_and_provenance(settings, setup_run):
    db, run, inputs, draft = setup_run
    requests, progress = [], []
    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        index = len(requests)
        if index == 1:
            return envelope(tools=[tool('search_web', {'query': 'Example platform'})])
        if index == 2:
            assert payload['messages'][-1]['tool_call_id'] == 'call_1'
            assert payload['messages'][-2]['reasoning_details']
            return envelope(tools=[tool('read_page', {'url': 'https://example.com/product'}, 'call_2')])
        if index == 3:
            assert 'Tools for reliable services.' in payload['messages'][-1]['content']
            return envelope(tools=[tool('search_web', {'query': 'Example engineering reliability'}, 'call_3')])
        if index == 4:
            return envelope(tools=[tool('read_page', {'url': 'https://example.com/engineering'}, 'call_4')])
        return envelope(json.dumps(draft))
    research = Research(settings, transport=httpx.MockTransport(zyte_response), progress=progress.append)
    ai = AI(settings, httpx.MockTransport(respond))
    result, call = ai.complete(db, 'write_cover_letter', inputs, s.LetterDraft, run_id=run, research=research)
    assert result.model_dump() == draft
    doc = r.save_document(db, run, 'cover_letter', result.content.model_dump(), ai_call_id=call)
    assert r.get(db, 'document_versions', doc)['ai_call_id'] == call
    calls = r.history(db, 'ai_calls', run_id=run)
    history = research_history(calls)
    assert history['status'] == 'completed' and history['stopping_reason'] == 'model_finished_after_research'
    assert history['searches'] == history['page_reads'] == 2
    assert len(history['sources']) == 2
    assert progress[-1] == 'drafting_cover_letter'
    assert all(item['status'] == 'succeeded' for item in calls)
    assert 'model-secret' not in json.dumps(calls) and 'zyte-secret' not in json.dumps(calls)
    app = create_app(settings, ai=ai)
    endpoint = next(route.endpoint for route in app.routes if route.path == '/api/v1/runs/{run_id}')
    detail = endpoint(run_id=run)
    assert detail['research']['status'] == 'completed'
    assert detail['research']['searches'] == 2
    assert len(detail['research']['sources']) == 2
    assert 'text' not in detail['research']['sources'][0]


def test_budget_errors_and_forced_final_schema(settings, setup_run):
    db, run, inputs, draft = setup_run
    settings = replace(settings, research_max_searches=1, research_max_pages=1, response_format='json_schema')
    research = Research(settings, transport=httpx.MockTransport(zyte_response))
    requests = []
    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            assert 'response_format' not in payload
            return envelope(tools=[tool('search_web', {'query': 'Example'}),
                tool('search_web', {'query': 'Other'}, 'call_2'),
                tool('read_page', {'url': 'https://example.com/product'}, 'call_3'),
                tool('read_page', {'url': 'https://example.com/extra'}, 'call_4')])
        observations = [json.loads(message['content']) for message in payload['messages'] if message['role'] == 'tool']
        assert observations[1]['error']['code'] == 'search_limit'
        assert observations[3]['error']['code'] == 'request_limit'
        assert payload['tool_choice'] == 'none'
        assert payload['response_format']['type'] == 'json_schema'
        return envelope(json.dumps(draft))
    AI(settings, httpx.MockTransport(respond)).complete(db, 'write_cover_letter', inputs, s.LetterDraft, run_id=run, research=research)
    assert research.reason == 'request_limit' and len(requests) == 2


@pytest.mark.parametrize('failure', ['unsupported', 'network', 'bad_envelope'])
def test_research_failures_fall_back(settings, setup_run, failure):
    db, run, inputs, draft = setup_run
    requests = []
    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            if failure == 'network':
                raise httpx.ConnectError('model-secret')
            if failure == 'bad_envelope':
                return httpx.Response(200, json={'choices': []})
            return httpx.Response(400, text='model-secret tools unsupported')
        assert 'tools' not in payload
        return envelope(json.dumps(draft))
    result, _ = AI(settings, httpx.MockTransport(respond)).complete(db, 'write_cover_letter', inputs, s.LetterDraft,
        run_id=run, research=Research(settings))
    assert result.model_dump() == draft and len(requests) == 2
    assert r.history(db, 'ai_calls', run_id=run)[0]['status'] == 'failed'


def test_schema_repair_keeps_evidence_and_disables_tools(settings, setup_run):
    db, run, inputs, draft = setup_run
    requests = []
    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            return envelope(tools=[tool('search_web', {'query': 'Example platform'}), tool('read_page', {'url': 'https://example.com/product'}, 'call_page')])
        if len(requests) == 2:
            return envelope('{"invalid":true}')
        assert 'tools' not in payload
        assert 'Tools for reliable services.' in json.dumps(payload['messages'])
        return envelope(json.dumps(draft))
    research = Research(settings, transport=httpx.MockTransport(zyte_response))
    _, call = AI(settings, httpx.MockTransport(respond)).complete(db, 'write_cover_letter', inputs, s.LetterDraft, run_id=run, research=research)
    assert r.get(db, 'ai_calls', call)['purpose'] == 'repair_write_cover_letter'
    assert len(requests) == 3


def test_turn_limit_prevents_invalid_request_loop(settings, setup_run):
    db, run, inputs, draft = setup_run
    requests = []
    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if payload['tool_choice'] == 'none':
            return envelope(json.dumps(draft))
        return envelope(tools=[tool('search_web', {}, 'call_' + str(len(requests)))])
    research = Research(settings)
    AI(settings, httpx.MockTransport(respond)).complete(db, 'write_cover_letter', inputs, s.LetterDraft, run_id=run, research=research)
    assert research.reason == 'turn_limit' and len(requests) == 17


def test_no_tools_for_other_operations(settings, setup_run):
    db, run, inputs, _ = setup_run
    def respond(request):
        assert 'tools' not in json.loads(request.content)
        return envelope('{"findings":[]}')
    AI(settings, httpx.MockTransport(respond)).complete(db, 'review_document', inputs, s.Review, run_id=run, research=Research(settings))


def test_settings_validation_and_environment(settings):
    for change in ({'research_max_searches': 0}, {'research_max_pages': 31}, {'research_timeout': 0}, {'zyte_search_domain': 'https://google.com'}):
        with pytest.raises(ValueError):
            replace(settings, **change)
    with patch('backend.config.load_dotenv'), patch.dict('os.environ', {
        'JAB_COVER_LETTER_RESEARCH_ENABLED': 'false', 'JAB_RESEARCH_MAX_SEARCHES': '3',
        'JAB_RESEARCH_MAX_PAGES': '4', 'JAB_RESEARCH_TIMEOUT': '90', 'JAB_ZYTE_SEARCH_DOMAIN': 'google.co.uk'}):
        loaded = Settings.load()
    assert not loaded.cover_letter_research_enabled
    assert (loaded.research_max_searches, loaded.research_max_pages, loaded.research_timeout) == (3, 4, 90)
    assert loaded.zyte_search_domain == 'google.co.uk'


def test_revision_reuses_sources_and_disabled_research(settings, setup_run):
    db, run, inputs, draft = setup_run
    research = Research(settings, transport=httpx.MockTransport(zyte_response))
    count = [0]
    def respond(request):
        count[0] += 1
        return envelope(tools=[tool('search_web', {'query': 'Example platform'}), tool('read_page', {'url': 'https://example.com/product'}, 'call_page')]) if count[0] == 1 else envelope(json.dumps(draft))
    result, call = AI(settings, httpx.MockTransport(respond)).complete(db, 'write_cover_letter', inputs, s.LetterDraft, run_id=run, research=research)
    doc = r.save_document(db, run, 'cover_letter', result.content.model_dump(), ai_call_id=call)
    r.finish_run(db, run)
    job = r.get(db, 'preparation_runs', run)['job_id']
    revision = r.create_run(db, job_id=job, source_document_id=doc, instructions='Improve opening only')
    class RevisionAI:
        def complete(self, db, operation, supplied, contract, **kwargs):
            assert 'research' not in kwargs
            assert operation == 'revise_document'
            assert 'Developer tools' in supplied['company_research']['sources'][0]['text']
            assert supplied['research_unavailable'] == 'disabled'
            revision_call = r.create_ai_call(db, purpose=operation, provider='fixture', model='fixture',
                request={'inputs': supplied}, run_id=kwargs['run_id'])
            output = s.LetterRevision(content=result.content, changes=['Improved opening'])
            r.finish_ai_call(db, revision_call, raw_response=output.model_dump_json(), validated_response=output.model_dump())
            return output, revision_call
    service = Service(replace(settings, cover_letter_research_enabled=False), ai=RevisionAI())
    with patch.object(service, 'render_document', return_value={}):
        service.generate(db, {'run_id': revision, 'id': -1})
    # Evidence is reused by the caller, never written into the frozen source snapshot.
    snapshot = json.loads(r.get(db, 'preparation_runs', revision)['source_snapshot_json'])
    assert 'company_research' not in snapshot


def test_interrupted_research_is_reported(settings, setup_run):
    db, run, inputs, _ = setup_run
    r.create_ai_call(db, purpose='write_cover_letter', provider=settings.base_url, model=settings.model,
        request={'research': Research(settings).metadata()}, run_id=run)
    d.recover_interrupted(db)
    history = research_history(r.history(db, 'ai_calls', run_id=run))
    assert history['status'] == 'stopped' and history['stopping_reason'] == 'interrupted'


@pytest.mark.parametrize('change', [{'cover_letter_research_enabled': False}, {'zyte_api_key': ''}])
def test_disabled_and_missing_credentials_never_advertise_tools(settings, setup_run, change):
    db, run, inputs, draft = setup_run
    def respond(request):
        assert 'tools' not in json.loads(request.content)
        return envelope(json.dumps(draft))
    configured = replace(settings, **change)
    AI(configured, httpx.MockTransport(respond)).complete(db, 'write_cover_letter', inputs, s.LetterDraft,
        run_id=run, research=Research(configured))


def test_service_enables_research_only_for_letter(settings, setup_run):
    db, original_run, inputs, draft = setup_run
    job = r.get(db, 'preparation_runs', original_run)['job_id']
    run = r.create_run(db, job_id=job)
    requests, progress = [], []
    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            assert 'tools' not in payload
            return envelope(json.dumps({'content': inputs['resume']}))
        if len(requests) == 2:
            return envelope(tools=[tool('search_web', {'query': 'Example platform'}), tool('read_page', {'url': 'https://company.example/product'}, 'call_page')])
        assert 'Tools for reliable services.' in payload['messages'][-1]['content']
        return envelope(json.dumps(draft))
    ai = AI(settings, httpx.MockTransport(respond))
    service = Service(settings, ai=ai)
    def executor(configuration, **kwargs):
        return Research(configuration, transport=httpx.MockTransport(zyte_response), **kwargs)
    with patch('backend.service.Research', side_effect=executor), patch.object(service, 'step', side_effect=lambda db, task, value: progress.append(value)), patch('backend.service.rendering.render', return_value=(b'%PDF-1.7\nfixture\n%%EOF', [])):
        result = service.generate(db, {'run_id': run, 'id': -1})
    assert len(result['document_ids']) == 2 and result['status'] == 'succeeded'
    assert 'researching_company' in progress and 'reading_company_page' in progress
    assert research_history(r.history(db, 'ai_calls', run_id=run))['page_reads'] == 1


def test_deadline_during_inference_forces_ordinary_final(settings, setup_run):
    db, run, inputs, draft = setup_run
    clock, requests = [0], []
    research = Research(settings, clock=lambda: clock[0])
    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            clock[0] = 301
            return envelope(tools=[tool('search_web', {'query': 'Example'})])
        assert payload['tool_choice'] == 'none'
        observed = next(json.loads(message['content']) for message in payload['messages'] if message['role'] == 'tool')
        assert observed['error']['code'] == 'time_limit'
        return envelope(json.dumps(draft))
    AI(settings, httpx.MockTransport(respond)).complete(db, 'write_cover_letter', inputs, s.LetterDraft, run_id=run, research=research)
    assert len(requests) == 2 and research.searches == 0


def test_retrieval_timeout_is_an_observation(settings):
    def timeout(request):
        raise httpx.ReadTimeout('zyte-secret')
    research = Research(settings, transport=httpx.MockTransport(timeout))
    result = research.execute(tool('search_web', {'query': 'Example'})['function'])
    assert result['error']['code'] == 'research_timeout' and research.searches == 1
    assert 'zyte-secret' not in json.dumps(result)


def test_native_schema_tool_rejection_during_finalization_falls_back(settings, setup_run):
    db, run, inputs, draft = setup_run
    requests = []
    research = Research(replace(settings, research_max_searches=1, research_max_pages=1), transport=httpx.MockTransport(zyte_response))
    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            return envelope(tools=[tool('search_web', {'query': 'Example'}), tool('read_page', {'url': 'https://example.com'}, 'call_2')])
        if len(requests) == 2:
            assert payload['tool_choice'] == 'none'
            return httpx.Response(400, text='Unsupported tools with schema')
        assert 'tools' not in payload
        assert 'Tools for reliable services.' in json.dumps(payload['messages'])
        return envelope(json.dumps(draft))
    AI(replace(settings, response_format='json_schema'), httpx.MockTransport(respond)).complete(db, 'write_cover_letter', inputs,
        s.LetterDraft, run_id=run, research=research)
    assert len(requests) == 3


@pytest.mark.parametrize('operation', ['write_cover_letter', 'revise_document'])
@pytest.mark.parametrize('model', ['model', 'anthropic/claude-sonnet-5.5'])
def test_forced_search_then_page_even_with_previous_sources(settings, setup_run, operation, model):
    db, run, inputs, draft = setup_run
    settings = replace(settings, model=model)
    inputs['company_research'] = {'sources': [{'url': 'https://example.com/old', 'text': 'Old evidence'}]}
    if operation == 'revise_document':
        draft = {**draft, 'changes': ['Improved opening']}
    requests = []
    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            assert payload['tool_choice'] == ('auto' if 'sonnet' in model else {'type': 'function', 'function': {'name': 'search_web'}})
            return envelope(tools=[tool('search_web', {'query': 'Example customer problems'})])
        if len(requests) == 2:
            assert payload['tool_choice'] == ('auto' if 'sonnet' in model else {'type': 'function', 'function': {'name': 'read_page'}})
            return envelope(tools=[tool('read_page', {'url': 'https://example.com/product'}, 'page')])
        assert payload['tool_choice'] == 'auto'
        return envelope(json.dumps(draft))
    contract = s.LetterRevision if operation == 'revise_document' else s.LetterDraft
    result, _ = AI(settings, httpx.MockTransport(respond)).complete(
        db, operation, inputs, contract, run_id=run,
        research=Research(settings, transport=httpx.MockTransport(zyte_response)))
    assert result.model_dump() == draft and len(requests) == 3


@pytest.mark.parametrize('skip_phase', ['search', 'page', 'wrong_tool'])
@pytest.mark.parametrize('model', ['model', 'anthropic/claude-sonnet-5.5'])
def test_ignored_required_research_rejects_letter_without_drafting_fallback(settings, setup_run, skip_phase, model):
    db, run, inputs, draft = setup_run
    settings = replace(settings, model=model)
    requests = []
    def respond(request):
        requests.append(json.loads(request.content))
        if skip_phase == 'page' and len(requests) == 1:
            return envelope(tools=[tool('search_web', {'query': 'Example'})])
        if skip_phase == 'wrong_tool':
            return envelope(tools=[tool('read_page', {'url': 'https://example.com'})])
        return envelope(json.dumps(draft))
    with pytest.raises(BackendError) as caught:
        AI(settings, httpx.MockTransport(respond)).complete(
            db, 'write_cover_letter', inputs, s.LetterDraft, run_id=run,
            research=Research(settings, transport=httpx.MockTransport(zyte_response)))
    assert caught.value.code == 'company_research_required'
    calls = r.history(db, 'ai_calls', run_id=run)
    assert calls[-1]['status'] == 'failed'
    assert research_history(calls)['stopping_reason'] == 'required_tool_skipped'
    assert research_history(calls)['status'] == 'stopped'
    assert len(requests) == (2 if skip_phase == 'page' else 1)
    assert r.history(db, 'document_versions', run_id=run) == []


@pytest.mark.parametrize('failed_tool', ['search_web', 'read_page'])
def test_failed_retrieval_exhausts_budget_with_honest_fallback(settings, setup_run, failed_tool):
    db, run, inputs, draft = setup_run
    cfg = replace(settings, research_max_searches=1, research_max_pages=1)
    def retrieve(request):
        is_search = request.url.path.endswith('/search')
        if is_search == (failed_tool == 'search_web'):
            return httpx.Response(500, text='zyte-secret')
        return zyte_response(request)
    requests = []
    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            return envelope(tools=[tool('search_web', {'query': 'Example'})])
        if failed_tool == 'read_page' and len(requests) == 2:
            return envelope(tools=[tool('read_page', {'url': 'https://example.com/product'}, 'page')])
        assert payload['tool_choice'] == 'none'
        return envelope(json.dumps(draft))
    AI(cfg, httpx.MockTransport(respond)).complete(
        db, 'write_cover_letter', inputs, s.LetterDraft, run_id=run,
        research=Research(cfg, transport=httpx.MockTransport(retrieve)))
    history = research_history(r.history(db, 'ai_calls', run_id=run))
    assert history['status'] == 'stopped'
    assert history['stopping_reason'] == ('search_limit' if failed_tool == 'search_web' else 'page_limit')
    assert not history['sources']
