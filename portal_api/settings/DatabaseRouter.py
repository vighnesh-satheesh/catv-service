class DatabaseRouter:
    def db_for_read(self, model, **hints):
        return 'readonly'

    def db_for_write(self, model, **hints):
        return 'default'

