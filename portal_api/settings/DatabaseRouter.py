class DatabaseRouter:
    def db_for_read(self, model, **hints):
        return 'readonly'

    def db_for_write(self, model, **hints):
        return 'default'

    def allow_relation(self, obj1, obj2, **hints):
        db_list = ('default', 'readonly')
        if obj1._state.db in db_list and obj2._state.db in db_list:
            return True
        return None
