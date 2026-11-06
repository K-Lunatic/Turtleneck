"""Explicit experimental activation; install before starting request threads."""
from contextlib import contextmanager
from python_adapter import RustParser, parser_class, overview_parser_class
from providers import moodle_provider
from features import concept_insights


@contextmanager
def activate(native=None, modules=('activity', 'overview')):
    if not modules:
        yield ()
        return
    try:
        native = native or RustParser()
    except (OSError, AttributeError):
        yield ()  # A missing optional DLL never breaks the existing Python application.
        return
    replacements = {'activity': (moodle_provider, '_ActivityParser', parser_class(native)),
                    'overview': (moodle_provider, '_SectionOverviewParser', overview_parser_class(native)),
                    'concept': (concept_insights, '_rank_bucket', native.rank_concepts)}
    previous = []
    try:
        for module in modules:
            target, name, replacement = replacements[module]
            previous.append((target, name, getattr(target, name)))
            setattr(target, name, replacement)
        yield tuple(modules)
    finally:
        for target, name, original in reversed(previous):
            setattr(target, name, original)
