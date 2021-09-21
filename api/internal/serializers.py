from collections import OrderedDict
from rest_framework import serializers

from ..serializers import CATVSerializer

class NonNullModelSerializer(serializers.ModelSerializer):
    def to_representation(self, instance):
        result = super(NonNullModelSerializer, self).to_representation(instance)
        return OrderedDict([(key, result[key]) for key in result if result[key] is not None])

class CATVInternalSerializer(CATVSerializer):
    source_depth = serializers.IntegerField(required=False, min_value=1, max_value=30)
    distribution_depth = serializers.IntegerField(required=False, min_value=1, max_value=30)

