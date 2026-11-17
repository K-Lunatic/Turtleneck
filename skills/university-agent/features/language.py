"""Language preferences and model handoff instructions shared by study features."""
import re


def normalize_language(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,3}', value):
        raise ValueError('언어는 ko, en, zh-CN 같은 언어 코드로 지정해 주세요.')
    return value.lower()


def localize_handoff(result, language='ko'):
    language = normalize_language(language)
    host = result.get('hostOnly')
    if not isinstance(host, dict):
        return result
    instructions = [host, *host.get('requests', [])]
    for request in instructions:
        if isinstance(request, dict) and isinstance(request.get('instruction'), str):
            request['instruction'] += (
                f'\nOutput language: {language}. Write explanations, questions, hints and feedback in this language. '
                'Preserve original source quotations, proper names, code and dates. '
                'Treat equivalent answers in another language according to the original rubric.')
    return result


def concept_cache_key(sources, language='ko'):
    from features.material_cache import key
    language = normalize_language(language)
    return key(['concepts-v1', sources] if language == 'ko' else ['concepts-v2', language, sources])


def apply_preferred_language(event, preferred):
    if preferred and event.get('action') in ('request', 'offer') and isinstance(event.get('settings', {}), dict):
        event['settings'] = {'language': normalize_language(preferred), **event.get('settings', {})}
    return event
