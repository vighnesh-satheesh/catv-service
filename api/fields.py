from six import text_type
from django.utils.text import Truncator
from django.db import models
from django.db.models import Lookup

from rest_framework import serializers


# Serializer
class EnumField(serializers.ChoiceField):
    def __init__(self, enum, **kwargs):
        self.enum = enum
        self.enum_re = {e.value: e for e in enum}
        kwargs['choices'] = [(e.name, e.name) for e in enum]
        super(EnumField, self).__init__(**kwargs)

    def to_representation(self, obj):
        return obj.value

    def to_internal_value(self, data):
        try:
            return self.enum_re[data]
        except KeyError:
            self.fail('invalid_choice', input=data)


class TruncatedCharField(serializers.CharField):
    default_truncate_len = 100
    default_placeholder = "..."

    def __init__(self, **kwargs):
        self.truncate_len = kwargs.pop("truncate_len", self.default_truncate_len)
        self.placeholder = kwargs.pop("placeholder", self.default_placeholder)
        super(TruncatedCharField, self).__init__(**kwargs)

    def to_representation(self, value):
        if len(value) <= self.truncate_len:
            return text_type(value)
        else:
            new_truncate_len = self.truncate_len - len(self.placeholder)
            return text_type(Truncator(value).chars(new_truncate_len,
                                                        truncate=self.placeholder))


# Model
class LtreeField(models.CharField):
    description = 'ltree (up to %(max_length)s)'

    def __init__(self, *args, **kwargs):
        kwargs['max_length'] = 1024
        super().__init__(*args, **kwargs)

    def db_type(self, connection):
        return 'ltree'

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        del kwargs['max_length']
        return name, path, args, kwargs


class LtreeLookup(Lookup):
    lookup_name = ""
    operator = ""

    def as_sql(self, qn, connection):
        lhs, lhs_params = self.process_lhs(qn, connection)
        rhs, rhs_params = self.process_rhs(qn, connection)
        params = lhs_params + rhs_params
        transform = ''
        if isinstance(self.rhs, list):
            transform = '::ltree[]'
        return '%s %s %s%s' % (lhs, self.operator, rhs, transform), params

    def get_prep_lookup(self):
        if hasattr(self.rhs, '_prepare'):
            return self.rhs._prepare(self.lhs.output_field)
        if self.prepare_rhs and hasattr(self.lhs.output_field, 'get_prep_value'):
            if isinstance(self.rhs, list):
                return self.rhs
            else:
                return self.lhs.output_field.get_prep_value(self.rhs)
        return self.rhs


class AncestorOrEqual(LtreeLookup):
    lookup_name = 'aore'
    operator = '@>'


LtreeField.register_lookup(AncestorOrEqual)


class DescendantOrEqual(LtreeLookup):
    lookup_name = 'dore'
    operator = '<@'


LtreeField.register_lookup(DescendantOrEqual)


class Match(Lookup):
    lookup_name = 'match'

    def as_sql(self, qn, connection):
        lhs, lhs_params = self.process_lhs(qn, connection)
        rhs, rhs_params = self.process_rhs(qn, connection)
        params = lhs_params + rhs_params
        return '%s ~ %s' % (lhs, rhs), params


LtreeField.register_lookup(Match)
