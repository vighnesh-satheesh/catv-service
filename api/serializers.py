import re
import time
from collections import OrderedDict

from dateutil import parser
from django.utils import timezone
from requests.exceptions import ReadTimeout
from rest_framework import serializers

from . import exceptions
from . import fields
from . import models
from . import utils
from .catvutils.tracking_results import (
    TrackingResults, BTCTrackingResults,
    BTCCoinpathTrackingResults, EthPathResults,
    BtcPathResults
)
from .catvutils.vendor_api import LyzeAPIInterface
from .models import CatvNodeLabelModel
from .settings import api_settings


class NonNullModelSerializer(serializers.ModelSerializer):
    def to_representation(self, instance):
        result = super(NonNullModelSerializer,
                       self).to_representation(instance)
        return OrderedDict([(key, result[key]) for key in result if result[key] is not None])

class CATVSerializer(serializers.Serializer):
    wallet_address = serializers.CharField(required=False, allow_blank=True)
    transaction_hash = serializers.CharField(required=False, allow_blank=True)
    source_depth = serializers.IntegerField(
        required=False, min_value=1, max_value=10)
    distribution_depth = serializers.IntegerField(
        required=False, min_value=1, max_value=10)
    transaction_limit = serializers.IntegerField(
        required=True, min_value=100, max_value=100000)
    from_date = serializers.CharField(required=True)
    to_date = serializers.CharField(required=True)
    token_address = serializers.CharField(
        required=False, default='0x0000000000000000000000000000000000000000')
    force_lookup = serializers.BooleanField(required=False, default=False)
        

    def validate(self, data):
        if 'source_depth' not in data and 'distribution_depth' not in data:
            raise serializers.ValidationError(
                "Either of source_depth or distribution_depth is needed.")

            # Check that exactly one of wallet_address or transaction_hash is provided
        wallet = data.get('wallet_address', '').strip()
        tx_hash = data.get('transaction_hash', '').strip()

        if not wallet and not tx_hash:
            raise serializers.ValidationError(
                "Either wallet_address or transaction_hash is required.")

        if wallet and tx_hash:
            raise serializers.ValidationError(
                "Provide either wallet_address or transaction_hash, not both.")

        return data

    def validate_wallet_address(self, value):
        if not value or not value.strip():
            return value

        if not utils.pattern_matches_token(value, self._token_type):
            raise serializers.ValidationError(
                "Wallet address is not a valid address for the specified token type.")
        return value

    def validate_transaction_hash(self, value):
        if not value or not value.strip():
            return value

        # EVM transaction hash: 0x followed by 64 hex characters
        evm_pattern = re.compile(r'^0x[a-fA-F0-9]{64}$')
        # TRON transaction hash: 64 hex characters (no 0x prefix)
        tron_pattern = re.compile(r'^[a-fA-F0-9]{64}$')

        if not (evm_pattern.match(value) or tron_pattern.match(value)):
            raise serializers.ValidationError(
                "Transaction hash must be a valid EVM (0x + 64 hex chars) or TRON (64 hex chars) transaction hash.")

        return value

    def validate_from_date(self, value):
        try:
            utils.validate_dateformat(value, '%Y-%m-%d')
            return value
        except ValueError:
            raise serializers.ValidationError(
                "Incorrect date format, should be YYYY-MM-DD.")

    def validate_to_date(self, value):
        try:
            utils.validate_dateformat(value, '%Y-%m-%d')
            return value
        except ValueError:
            raise serializers.ValidationError(
                "Incorrect date format, should be YYYY-MM-DD.")

    def get_tracking_results(self, tx_limit=10000, limit=10000, save_to_db=True, build_lossy_graph=True):
        tracking_results = TrackingResults(**self.data, chain=self._token_type)
        try:
            tracking_results.get_tracking_data(tx_limit, limit, save_to_db)
            tracking_results.create_graph_data(build_lossy_graph)
            tracking_results.set_annotations_from_db(
                token_type=models.CatvTokens.ETH.value)
            return {
                "graph": tracking_results.make_graph_dict(),
                "api_calls": tracking_results.ext_api_calls,
                "messages": tracking_results.error_messages
            }
        except ReadTimeout:
            raise exceptions.FileNotFound("Timeout exceeded while fetching/processing data.")
        except Exception as e:
            print(e)
            err_msg = "Incorrect or missing transactions. Please try adjusting your search criteria."
            if tracking_results.error:
                err_msg = tracking_results.error
            elif e:
                err_msg = "Oops! Something went wrong while getting results for this address. Please try again later."
            raise exceptions.FileNotFound(err_msg)


class CATVBTCSerializer(CATVSerializer):
    tx_hash = serializers.CharField(required=True)

    def validate_wallet_address(self, value):
        pattern = re.compile("^([13]|bc1).*[a-zA-Z0-9]{26,35}$")
        if not pattern.match(value):
            raise serializers.ValidationError(
                "Wallet address is an invalid Bitcoin address")
        return value

    def valid_tx_hash(self, value):
        pattern = re.compile("^[a-fA-F0-9]{64}$")
        if not pattern.match(value):
            raise serializers.ValidationError(
                "Transaction hash is an invalid Bitcoin transaction hash")
        return value

    def get_tracking_results(self, tx_limit=10, limit=10, save_to_db=True, build_lossy_graph=True):
        serializer_data = self.data
        tracking_results = BTCTrackingResults(**serializer_data)
        try:
            tracking_results.get_tracking_data(tx_limit, limit, save_to_db)
            tracking_results.create_graph_data(
                serializer_data["wallet_address"], build_lossy_graph)
            tracking_results.set_annotations_from_db(
                token_type=models.CatvTokens.BTC.value)
            return {
                "graph": tracking_results.make_graph_dict(),
                "api_calls": tracking_results.ext_api_calls,
                "messages": tracking_results.error_messages
            }
        except ReadTimeout:
            raise exceptions.FileNotFound("Timeout exceeded while fetching/processing data.")
        except Exception as e:
            err_msg = "Incorrect or missing transactions. Please try adjusting your search criteria."
            if tracking_results.error:
                err_msg = tracking_results.error
            elif e:
                err_msg = "Oops! Something went wrong while getting results for this address. Please try again later."
            raise exceptions.FileNotFound(err_msg)


class CATVBTCTxlistSerializer(serializers.Serializer):
    wallet_address = serializers.CharField(required=True)
    from_date = serializers.CharField(required=True)
    to_date = serializers.CharField(required=True)

    def validate_wallet_address(self, value):
        pattern = re.compile("^([13]|bc1).*[a-zA-Z0-9]{26,35}$")
        if not pattern.match(value):
            raise serializers.ValidationError(
                "Wallet address is an invalid Bitcoin address")
        return value

    def validate_from_date(self, value):
        try:
            utils.validate_dateformat(value, '%Y-%m-%d')
            return value
        except ValueError:
            raise serializers.ValidationError(
                "Incorrect date format, should be YYYY-MM-DD.")

    def validate_to_date(self, value):
        try:
            utils.validate_dateformat(value, '%Y-%m-%d')
            return value
        except ValueError:
            raise serializers.ValidationError(
                "Incorrect date format, should be YYYY-MM-DD.")

    def get_btc_txlist(self):
        txlist_client = LyzeAPIInterface(api_settings.LYZE_API_KEY)
        data = self.data
        resp = txlist_client.get_txlist(
            data['wallet_address'], data['from_date'], data['to_date'])
        txlist = []
        seen_txid = []
        for tx in resp:
            tx_dict = {}
            if tx['tx_id'].lower() not in seen_txid:
                for k, v in tx.items():
                    if k == 'tx_id' or k == 'ts':
                        tx_dict[k] = v
                txlist.append(tx_dict)
                seen_txid.append(tx['tx_id'].lower())
        return txlist


class CATVBTCCoinpathSerializer(CATVSerializer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def validate_wallet_address(self, value):
        if not value or not value.strip():
            return value

        if not utils.pattern_matches_token(value, self._token_type):
            raise serializers.ValidationError(
                "Wallet address is not a valid address for the specified token type.")
        return value

    def validate_transaction_hash(self, value):
        if not value or not value.strip():
            return value

        # BTC transaction hash: 64 hex characters (no 0x prefix)
        btc_pattern = re.compile(r'^[a-fA-F0-9]{64}$')

        if not btc_pattern.match(value):
            raise serializers.ValidationError(
                "Transaction hash must be a valid BTC (64 hex chars) transaction hash.")

        return value

    def get_tracking_results(self, tx_limit=10000, limit=10000, save_to_db=True, build_lossy_graph=True):
        serializer_data = self.data
        tracking_results = BTCCoinpathTrackingResults(**serializer_data, chain=self._token_type)
        try:
            tracking_results.get_tracking_data(tx_limit, limit, save_to_db)
            tracking_results.create_graph_data(build_lossy_graph)
            tracking_results.set_annotations_from_db(
                token_type=models.CatvTokens.BTC.value)
            return {
                "graph": tracking_results.make_graph_dict(),
                "api_calls": tracking_results.ext_api_calls,
                "messages": tracking_results.error_messages
            }
        except ReadTimeout:
            raise exceptions.FileNotFound("Timeout exceeded while fetching/processing data.")
        except Exception as e:
            err_msg = "Incorrect or missing transactions. Please try adjusting your search criteria."
            if tracking_results.error:
                err_msg = tracking_results.error
            elif e:
                err_msg = "Oops! Something went wrong while getting results for this address. Please try again later."
            raise exceptions.FileNotFound(err_msg)

class CATVHistorySerializer(serializers.Serializer):
    token_type = fields.EnumField(enum=models.CatvTokens, required=True)
    path_search = serializers.BooleanField(default=False, required=False)

    def validate_token_type(self, data):
        valid_tokens = [token.value for token in models.CatvTokens]
        if not data or data.value.upper() not in valid_tokens:
            raise serializers.ValidationError("Token type unsupported.")
        return data


class CATVEthPathSerializer(serializers.Serializer):
    address_from = serializers.CharField(required=True)
    address_to = serializers.CharField(required=True)
    token_address = serializers.CharField(
        required=False, default='0x0000000000000000000000000000000000000000')
    depth = serializers.IntegerField(
        required=False, min_value=1, max_value=10, default=5)
    from_date = serializers.CharField(
        required=False, default=timezone.datetime(2015, 1, 1).strftime('%Y-%m-%d'))
    to_date = serializers.CharField(
        required=False, default=timezone.now().strftime('%Y-%m-%d'))
    min_tx_amount = serializers.FloatField(required=False, default=0.0)
    limit_address_tx = serializers.IntegerField(required=False, default=100000)
    force_lookup = serializers.BooleanField(required=False, default=False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._tracker = EthPathResults

    def validate_address_from(self, value):
        if not utils.pattern_matches_token(value, self._token_type):
            raise serializers.ValidationError(
                "Wallet address 'address_form' is not a valid ethereum address.")
        return value

    def validate_address_to(self, value):
        if not utils.pattern_matches_token(value, self._token_type):
            raise serializers.ValidationError(
                "Wallet address 'address_to' is not a valid ethereum address.")
        return value

    def validate_from_date(self, value):
        try:
            utils.validate_dateformat(value, '%Y-%m-%d')
            return value
        except ValueError:
            raise serializers.ValidationError(
                "Incorrect date format, should be YYYY-MM-DD.")

    def validate_to_date(self, value):
        try:
            utils.validate_dateformat(value, '%Y-%m-%d')
            return value
        except ValueError:
            raise serializers.ValidationError(
                "Incorrect date format, should be YYYY-MM-DD.")

    def validate(self, data):
        if data['address_from'].lower() == data['address_to'].lower():
            raise serializers.ValidationError("Source and destination addresses cannot be same. Perhaps you meant to "
                                              "use the '/catv' resource?")
        return data

    def get_tracking_results(self, save_to_db=False):
        tracking_instance = self._tracker(**self.data, chain=self._token_type)
        try:
            tracking_instance.get_tracking_data()
            tracking_instance.create_graph_data()
            tracking_instance.set_annotations_from_db(
                token_type=self._token_type)
            return {
                "graph": tracking_instance.make_graph_dict(),
                "api_calls": tracking_instance.ext_api_calls,
                "messages": tracking_instance.error_messages
            }
        except ReadTimeout:
            raise exceptions.FileNotFound("Timeout exceeded while fetching/processing data.")
        except Exception as e:
            import traceback
            traceback.print_exc()
            err_msg = "Incorrect or missing transactions. Please try adjusting your search criteria."
            if tracking_instance.error:
                err_msg = tracking_instance.error
            elif e:
                err_msg = "Oops! Something went wrong while getting results for this address. Please try again later."
            raise exceptions.FileNotFound(err_msg)


class CatvBtcPathSerializer(CATVEthPathSerializer):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._tracker = BtcPathResults

    def validate_address_from(self, value):
        if not utils.pattern_matches_token(value, self._token_type):
            raise serializers.ValidationError(
                "Wallet address 'address_form' is not a valid bitcoin address.")
        return value

    def validate_address_to(self, value):
        if not utils.pattern_matches_token(value, self._token_type):
            raise serializers.ValidationError(
                "Wallet address 'address_to' is not a valid bitcoin address.")
        return value

class CATVRequestListSerializer(NonNullModelSerializer):
    wallet_address = serializers.SerializerMethodField()
    transaction_hash = serializers.SerializerMethodField()
    address_type = serializers.SerializerMethodField()
    date_range = serializers.SerializerMethodField()
    depth = serializers.SerializerMethodField()
    status = fields.EnumField(enum=models.CatvTaskStatusType)
    created = serializers.SerializerMethodField()
    updated = serializers.SerializerMethodField()
    token_address = serializers.SerializerMethodField()
    token_type = fields.EnumField(enum=models.CatvTokens)
    labels = serializers.ListField(child=serializers.CharField(), required=False, read_only=True)
    user_error_message = serializers.CharField(source='error_message', read_only=True)

    class Meta:
        model = models.CatvRequestStatus
        fields = ("id", "uid", "created", "updated", "status", "wallet_address", "transaction_hash",
                  "address_type", "date_range", "depth", "token_address", "token_type", "labels", "user_error_message", "is_legacy")
        read_only_fields = ("id", "uid", "created", "updated", "status", "wallet_address", "transaction_hash",
                            "address_type", "date_range", "depth", "token_address", "token_type", "labels", "user_error_message", "is_legacy")

    def get_wallet_address(self, obj):
        if obj.params:
            # Check for path search first (has address_from)
            if obj.params.get("address_from", ""):
                return obj.params["address_from"]
            # Then check for flow search wallet_address
            return obj.params.get("wallet_address", "")
        return ""

    def get_transaction_hash(self, obj):
        """Extract transaction_hash from params if available"""
        if obj.params:
            return obj.params.get("transaction_hash", "")
        return ""

    def get_address_type(self, obj):
        if obj.token_type:
            return utils.determine_wallet_type(obj.token_type)
        return "Ethereum/ERC20"

    def get_date_range(self, obj):
        if obj.params:
            from_date = parser.parse(obj.params.get("from_date", "2015-01-01")).strftime("%d/%m/%Y")
            to_date = parser.parse(obj.params.get("to_date", "2020-01-01")).strftime("%d/%m/%Y")
            return f"{from_date} - {to_date}"
        return ""

    def get_depth(self, obj):
        if obj.params:
            if obj.params.get("depth", 0) > 0:
                return obj.params["depth"]
            else:
                source_depth = obj.params.get("source_depth", 0)
                distribution_depth = obj.params.get("distribution_depth", 0)
                return f"{source_depth} / {distribution_depth}"
        return ""

    def get_created(self, obj):
        if obj.created is None:
            return None
        return time.mktime(obj.created.timetuple()) * 1000

    def get_updated(self, obj):
        if obj.updated is None:
            return None
        return time.mktime(obj.updated.timetuple()) * 1000

    def get_token_address(self, obj):
        if obj.params:
            return obj.params.get("token_address", "")
        return ""

class CATVNodeLabelPostSerializer(serializers.ModelSerializer):
    uid = serializers.CharField(required=True)
    wallet_address = serializers.CharField(required=True)
    label = serializers.CharField(required=True)
    class Meta:
        model = CatvNodeLabelModel
        fields = ("id", "uid", "wallet_address", "user_id", "label")
        read_only_fields = ("id", "user_id")

    def create(self, validated_data):
        # Check if label already exists for this wallet and uid for the user
        existing_label = CatvNodeLabelModel.objects.filter(
            uid=validated_data['uid'],
            wallet_address=validated_data['wallet_address'],
            user_id=validated_data['user_id']
        ).first()

        if existing_label:
            # Update existing label
            existing_label.label = validated_data['label']
            existing_label.save()
            return existing_label

        # Create new label if it doesn't exist
        return super().create(validated_data)
