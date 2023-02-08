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
