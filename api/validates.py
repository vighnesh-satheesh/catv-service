from django.core.exceptions import ValidationError
import django.contrib.auth.password_validation as password_validator

from rest_framework import exceptions

from web3 import Web3

from . import models
from .cache import DefaultCache


def validate_pattern_type_subtype(pattern_type, pattern_subtype, model=False):
    exc_class = ValidationError if model is True else exceptions.ValidationError

    if pattern_type == models.IndicatorPatternType.NETWORKADDR:
        if pattern_subtype not in models.IndicatorPatternSubtype.networkaddr_subtypes():
            raise exc_class({"pattern_subtype": "pattern_subtype should be one of network address subtype"})
    elif pattern_type == models.IndicatorPatternType.CRYPTOADDR:
        if pattern_subtype not in models.IndicatorPatternSubtype.cryptoaddr_subtypes():
            raise exc_class({"pattern_subtype": "pattern_subtype should be one of crypto address subtype"})
    elif pattern_type == models.IndicatorPatternType.FILEHASH:
        if pattern_subtype not in models.IndicatorPatternSubtype.filehash_subtypes():
            raise exc_class({"pattern_subtype": "pattern_subtype should be one of file hash subtype"})
    elif pattern_type == models.IndicatorPatternType.SOCIALMEDIA:
        if pattern_subtype not in models.IndicatorPatternSubtype.socialmedia_subtypes():
            raise exc_class({"pattern_subtype": "pattern_subtype should be one of social media subtype"})
    elif pattern_type == models.IndicatorPatternType.OTHER:
        if pattern_subtype != models.IndicatorPatternSubtype.OTHER:
            raise exc_class({"pattern_subtype": "pattern_subtype should be other when pattern_type is other"})


def validate_indicator_vector(vector, model=False):
    exc_class = ValidationError if model is True else exceptions.ValidationError

    if not vector:
        return

    if len(set(vector) - set(models.IndicatorVector.indicator_vector_type())) > 0:
        raise exc_class({"vector":  "now allowed vector type"})


def validate_indicator_environment(environment, model=False):
    exc_class = ValidationError if model is True else exceptions.ValidationError

    if not environment:
        return

    if len(set(environment) - set(models.IndicatorEnvironment.indicator_environment_type())) > 0:
        raise exc_class({"environment":  "now allowed environment type"})


def validate_security_type_tag(security_category, security_tag, model=False):
    exc_class = ValidationError if model is True else exceptions.ValidationError

    if security_tag is None:
        return
    elif isinstance(security_tag, list) and len(security_tag) == 0:
        return
    elif not isinstance(security_tag, list):
        raise exc_class({"security_tags": "list of string is required."})
    else:
        c = DefaultCache()
        tags = c.get_s_tags()
        if not tags:
            tags = models.SecurityTag.objects.all().values_list('tag', flat=True)
            c.set_s_tags(list(tags))
        if not set(security_tag).issubset(set(tags)):
            raise exc_class({"security_tags": "security tags should be picked from the system defined list of tags"})


def validate_max_length(text, model=False, limit=128, field_name="text"):
    exc_class = ValidationError if model is True else exceptions.ValidationError

    if len(text) > limit:
        raise exc_class({field_name: "The length of {0} should be less than {1}".format(field_name, limit)})


def validate_password(user, password, model=False):
    exc_class = ValidationError if model is True else exceptions.ValidationError
    try:
        password_validator.validate_password(password, user=user)
    except ValidationError as err:
        message = "minimum 8 charater. common or numeric password not allowed."
        if isinstance(err.messages, list):
            message = " ".join(err.messages)
        else:
            message = str(err.messages)
        raise exc_class({"password": message})


def get_validated_checksum_addr(pattern, node_url, model=False):
    exc_class = ValidationError if model else exceptions.ValidationError
    try:
        web3_client = Web3(Web3.HTTPProvider(node_url))
        return web3_client.toChecksumAddress(pattern)
    except ValueError:
        raise exc_class({"pattern": "Incorrect Ethereum address provided"})
