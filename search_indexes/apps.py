try:
    from django.apps import AppConfig

    class Config(AppConfig):
        name = 'search_indexes'
        label = 'search_indexes'

    __all__ = ('Config',)

except ImportError:
    pass
