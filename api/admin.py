import json

from web3 import Web3 as Web3
from dateutil.relativedelta import relativedelta
from django.contrib import admin
from django.contrib.admin.filters import ChoicesFieldListFilter
from django.utils import timezone
from django.utils.encoding import force_text
from django.utils.translation import ugettext_lazy as _
from django.contrib.auth.hashers import (check_password, make_password)
import django.forms as forms
from django.core.exceptions import ObjectDoesNotExist
from django.db import connection

# import ModelForm, PasswordInput
from api.email.tasks import SendEmail
from .models import (
    Indicator, ICO, Case, CaseHistory,
    AttachedFile, User, UserStatus,
    UppwardRewardInfo, CaseInvalidateCandidates,
    Key, EmailSent, Action, Role, RolePermission, RoleUsageLimit,
    RewardSetting, OrganizationUser, OrganizationInvites,
    OrganizationInviteStatus, OrganizationUserStatus, Usage,
    ExchangeToken, ExchangeStatus)
from .email import Email
from .settings import api_settings
from .constants import Constants


def execute_custom_query(query, data=None):
    with connection.cursor() as cursor:
        if data:
            cursor.execute(query, data)
        else:
            cursor.execute(query)


class EnumFieldListFilter(ChoicesFieldListFilter):
    def choices(self, cl):
        yield {
            'selected': self.lookup_val is None,
            'query_string': cl.get_query_string({}, [self.lookup_kwarg]),
            'display': _('All'),
        }
        for enum_value in self.field.enum:
            str_value = force_text(enum_value.value)
            yield {
                'selected': (str_value == self.lookup_val),
                'query_string': cl.get_query_string({self.lookup_kwarg: str_value}),
                'display': force_text(enum_value.name),
                # 'display': getattr(enum_value, 'label', None) or force_text(enum_value),
            }

    def queryset(self, request, queryset):
        try:
            self.field.enum(self.lookup_val)
        except ValueError:
            # since `used_parameters` will always contain strings,
            # for non-string-valued enums we'll need to fall back to attempt a slower
            # linear stringly-typed lookup.
            for enum_value in self.field.enum:
                if force_text(enum_value.value) == self.lookup_val:
                    self.used_parameters[self.lookup_kwarg] = enum_value
                    break
        return super(EnumFieldListFilter, self).queryset(request, queryset)


class ApprovalForm(forms.ModelForm):
    def clean(self):
        super(ApprovalForm, self).clean()

    def save(self, commit=True):
        m = super(ApprovalForm, self).save(commit=False)
        if m.status == ExchangeStatus.APPROVED:
            ganache_url = "https://ropsten.infura.io/v3/d13029c37e3b4c3880b9d473cb4d99a3"
            web3 = Web3(Web3.HTTPProvider(ganache_url))
            print("url:", ganache_url)
            print("Connected:", web3.isConnected())
            address = '0x755b72ba19462B49Db0377b28d2AEAF38E8ad217'
            key = '66007BEC9450ACC1FCD5BBCA36C9FAF312A326130A747DC8EEA307E3A4DF9199'
            nonce = web3.eth.getTransactionCount(web3.toChecksumAddress('0x7e62Dd2711261A79404Bf5EF977e2eF74E89E9CC'))
            print("nonce:", nonce)


            abi = json.loads(
                "[{\"constant\":false,\"inputs\":[{\"internalType\":\"address\",\"name\":\"addressUser\",\"type\":\"address\"}],\"name\":\"balanceOf\",\"outputs\":[{\"internalType\":\"uint256\",\"name\":\"\",\"type\":\"uint256\"}],\"payable\":false,\"stateMutability\":\"nonpayable\",\"type\":\"function\"},{\"constant\":false,\"inputs\":[{\"internalType\":\"uint256\",\"name\":\"amount_\",\"type\":\"uint256\"},{\"internalType\":\"address\",\"name\":\"addressUser\",\"type\":\"address\"}],\"name\":\"swap\",\"outputs\":[],\"payable\":true,\"stateMutability\":\"payable\",\"type\":\"function\"},{\"constant\":false,\"inputs\":[],\"name\":\"totalSupply\",\"outputs\":[{\"internalType\":\"uint256\",\"name\":\"\",\"type\":\"uint256\"}],\"payable\":false,\"stateMutability\":\"nonpayable\",\"type\":\"function\"},{\"inputs\":[],\"payable\":false,\"stateMutability\":\"nonpayable\",\"type\":\"constructor\"},{\"anonymous\":false,\"inputs\":[{\"indexed\":true,\"internalType\":\"address\",\"name\":\"from_\",\"type\":\"address\"},{\"indexed\":true,\"internalType\":\"address\",\"name\":\"to_\",\"type\":\"address\"},{\"indexed\":false,\"internalType\":\"uint256\",\"name\":\"amount_\",\"type\":\"uint256\"}],\"name\":\"TransferSuccessful\",\"type\":\"event\"},{\"anonymous\":false,\"inputs\":[{\"indexed\":true,\"internalType\":\"bool\",\"name\":\"value1\",\"type\":\"bool\"}],\"name\":\"test_value\",\"type\":\"event\"},{\"constant\":true,\"inputs\":[],\"name\":\"ERC20Interface\",\"outputs\":[{\"internalType\":\"contract ERC20\",\"name\":\"\",\"type\":\"address\"}],\"payable\":false,\"stateMutability\":\"view\",\"type\":\"function\"},{\"constant\":true,\"inputs\":[],\"name\":\"owner\",\"outputs\":[{\"internalType\":\"address\",\"name\":\"\",\"type\":\"address\"}],\"payable\":false,\"stateMutability\":\"view\",\"type\":\"function\"},{\"constant\":true,\"inputs\":[{\"internalType\":\"uint256\",\"name\":\"\",\"type\":\"uint256\"}],\"name\":\"transactions\",\"outputs\":[{\"internalType\":\"address\",\"name\":\"contract_\",\"type\":\"address\"},{\"internalType\":\"address\",\"name\":\"to_\",\"type\":\"address\"},{\"internalType\":\"uint256\",\"name\":\"amount_\",\"type\":\"uint256\"},{\"internalType\":\"bool\",\"name\":\"failed_\",\"type\":\"bool\"}],\"payable\":false,\"stateMutability\":\"view\",\"type\":\"function\"}]")
            contract = web3.eth.contract(address=address, abi=abi)
            txn = contract.functions.swap(m.upp*1000000000000000000, web3.toChecksumAddress('0xb7Cc1F87d32d08964Ae77A0f036a337f6De8D666')).buildTransaction({'from': web3.toChecksumAddress('0x7e62Dd2711261A79404Bf5EF977e2eF74E89E9CC'), 'nonce': nonce})
            print('txn:', txn)
            sign_txn = web3.eth.account.signTransaction(txn, private_key=key)
            print("signed:", sign_txn.rawTransaction)
            print("test", web3.eth.sendRawTransaction(sign_txn.rawTransaction))
            user = User.objects.get(uid__exact=m.user_id)
            if user and user.email_notification:
                e = Email()
                kv = {
                    "nickname": user.nickname,
                    "text": Constants.EMAIL_BODY["EXCHANGE_TOKEN_UP_BODY"].format("APPROVED")
                }
                SendEmail().delay(kv=kv,
                                  subject=Constants.EMAIL_TITLE["EXCHANGE_TOKEN_UPDATE"].format(
                                      "APPROVED"),
                                  email_type=e.EMAIL_TYPE["EXCHANGE_SUBMIT"],
                                  attachment=None,
                                  sender=e.EMAIL_SENDER["NO-REPLY"],
                                  recipient=[user.email])

           # print("test2", contract.functions.getApprovalList().call()[0])
        if m.status == ExchangeStatus.REJECTED:
            reject_points_query = Constants.QUERIES['UPDATE_USER_POINTS_QUERY_REJECT'].format(m.sp_amount, m.user_id)
            with connection.cursor() as cursor:
                cursor.execute(reject_points_query)
        if commit:
            m.save()
        return m


class UserForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput(), required=False)
    confirm_password = forms.CharField(widget=forms.PasswordInput(), required=False)

    class Meta:
        model = User
        fields = "__all__"

    def clean(self):
        cleaned_data = super(UserForm, self).clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")

        if password != confirm_password:
            raise forms.ValidationError(
                {"password": "password and confirm_password does not match"}
            )

        if not password:
            cleaned_data.pop("password")
            cleaned_data.pop("confirm_password")

        return cleaned_data

    def save(self, commit=True):
        m = super(UserForm, self).save(commit=False)
        try:
            user = User.objects.get(pk = m.pk)
            if user.password != m.password:
                m.password = make_password(m.password)
            if user.status == UserStatus.EMAIL_CONFIRMED and m.status == UserStatus.APPROVED:
                api_key_object, is_created = Key.objects.get_or_create(user=user)
                if is_created:
                    api_key_object.expire_datetime = timezone.now() + relativedelta(years=+1)
                    api_key_object.save()

                e = Email()
                e.sendemail(
                    kv = {
                        "nickname": user.nickname,
                        "link": api_settings.WEB_URL
                    },
                    subject = Constants.EMAIL_TITLE["VERIFIED"],
                    email_type = e.EMAIL_TYPE["VERIFIED"],
                    sender = e.EMAIL_SENDER["NO-REPLY"],
                    recipient = [user.email]
                )

                user_role = RoleUsageLimit.objects.get(role=user.role)
                usage_role_object, is_created = Usage.objects.get_or_create(user=user)
                if is_created:
                    usage_role_object.api_calls_left = user_role.api_limit
                    usage_role_object.catv_calls_left = user_role.catv_limit
                    usage_role_object.cara_calls_left = user_role.cara_limit
                    usage_role_object.last_renewal_at = timezone.now()
                    usage_role_object.save()

                org_invites = OrganizationInvites.objects.select_related('organization').\
                    get(email=user.email, status=OrganizationInviteStatus.PENDING_APPROVAL.value)
                if org_invites:
                    OrganizationUser.objects.create(organization=org_invites.organization, user=user,
                                                    status=OrganizationUserStatus.ACTIVE)
                    org_invites.status = OrganizationInviteStatus.APPROVED
                    org_invites.save()
            if user.status == UserStatus.APPROVED and m.status == UserStatus.APPROVED and user.role_id != m.role_id:
                query = Constants.QUERIES['UPDATE_USER_USAGE_QUOTA']
                data = (m.role_id, user.id,)
                execute_custom_query(query, data)
        except OrganizationInvites.DoesNotExist:
            pass
        except ObjectDoesNotExist:
            m.set_password(self.cleaned_data["password"])
        except Exception:
            pass
        if commit:
            m.save()
        return m


class UserAdmin(admin.ModelAdmin):
    form = UserForm

    list_display = ('id', 'uid', 'email', 'nickname', 'permission', 'role')
    list_display_links = ('id', 'uid')
    list_filter = [('permission', EnumFieldListFilter), ('status', EnumFieldListFilter), 'role', ]
    search_fields = ('id', 'email', 'nickname')
    fields = ('id', 'uid', 'password', 'confirm_password', 'email', 'nickname', 'created', 'permission', 'status',
              'email_notification', 'role')
    readonly_fields = ('id', 'uid', 'created')


class IndicatorAdmin(admin.ModelAdmin):
    list_display = ('id', 'uid', 'security_category', 'pattern_type', 'pattern_subtype', 'short_pattern')
    list_display_links = ('id', 'uid')
    list_filter = [('pattern_type', EnumFieldListFilter), ('security_category', EnumFieldListFilter)]
    search_fields = ('id', 'pattern')
    fields = ('id', 'uid', 'security_category', 'security_tags', 'pattern', 'pattern_type', 'pattern_subtype', 'detail', 'annotation', 'vector', 'environment')
    readonly_fields = ('id', 'uid')


class IndicatorInline(admin.TabularInline):
    model = Indicator
    extra = 0

    fields = ("id", "uid", "pattern_type", "pattern_subtype", "security_category", "pattern")
    readonly_fields = ("id", "uid", "pattern_type", "pattern_subtype", "security_category", "pattern")


class CaseHistoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'log', 'created')
    list_display_links = ('id',)


class CaseHistoryInline(admin.TabularInline):
    model = CaseHistory
    extra = 0

    fields = ("id", "log", "created")
    readonly_fields = ("id", "log", "created")


class ICOAdmin(admin.ModelAdmin):
    list_display = ('id', 'uid', 'name', 'symbol', 'website', 'type')
    list_display_links = ('id', 'uid')
    search_fields = ('id', 'name', 'symbol')


class CaseAdmin(admin.ModelAdmin):
    list_display = ('id', 'uid', 'title', 'status', 'owner_id')
    list_display_links = ('id', 'uid')
    list_filter = [('status', EnumFieldListFilter)]
    search_fields = ('id', 'title')
    fields = ('id', 'uid', 'title', 'detail', 'created', 'status', 'reporter_info', 'reporter', 'owner', 'verifier', 'block_num', 'transaction_id', 'ico',)
    raw_id_fields = ('reporter', 'owner', 'verifier', 'ico')
    readonly_fields = ('id', 'uid', 'created',)

    inlines = [
        CaseHistoryInline,
    ]


class AttachedFileAdmin(admin.ModelAdmin):
    list_display = ('id', 'uid', 'name', 'hash', 'type', 'case_id', 'link')
    list_display_links = ('id', 'uid', 'name')
    fields = ('file', 'uid', 'name', 'hash', 'size', 'type', 'case')
    raw_id_fields = ('case',)
    search_fields = ('id', 'uid')
    readonly_fields = ('name', 'uid', 'hash', 'size', 'type')


class UppwardRewardInfoAdmin(admin.ModelAdmin):
    list_display = ('id', 'aid', 'uid', 'cid', 'referral_code', 'token_addr', 'created')
    list_display_links = ('id', 'aid', 'uid', 'cid')
    fields = ('id', 'aid', 'uid', 'cid', 'referral_code', 'token_addr', 'created')
    readonly_fields = ('id', 'aid', 'uid', 'cid', 'referral_code', 'token_addr', 'created')


class CaseInvalidateCandidatesAdmin(admin.ModelAdmin):
    list_display = ('id', 'case', 'old_status', 'new_status', 'created')
    list_display_links = ('id', 'case')
    fields = ('id', 'case', 'old_status', 'new_status', 'created')
    readonly_fields = ('id', 'created')


class KeyAdmin(admin.ModelAdmin):
    list_display = ('id', 'api_key', 'request_assign', 'request_current', 'expire_datetime', 'type_id', 'user', 'created')
    list_display_links = ('id', 'user')
    list_filter = [('type_id', EnumFieldListFilter),]
    fields = ('id', 'api_key', 'request_assign', 'request_current', 'expire_datetime', 'type_id', 'user', 'created')
    readonly_fields = ('id', 'created', 'user')


class ExchangeAdmin(admin.ModelAdmin):
    form = ApprovalForm
    list_display = ('id', 'user_id', 'sp_amount', 'req_time', 'upp', 'status')
    list_filter = [('status', EnumFieldListFilter),]
    fields = ('id', 'user_id', 'sp_amount', 'req_time', 'upp', 'status')
    readonly_fields = ('id', 'user_id', 'sp_amount', 'upp', 'req_time')


class EmailSentAdmin(admin.ModelAdmin):
    list_display = ('id', 'email', 'created', 'type')
    fields = ('id', 'email', 'type', 'created')
    readonly_fields = ('id', 'email', 'type', 'created')


class ActionAdmin(admin.ModelAdmin):
    list_display = ('resource', 'action', 'codename')
    fields = ('resource', 'action', 'codename')
    readonly_fields = ('resource', 'action', 'codename')


class RolePermissionAdmin(admin.ModelAdmin):
    fields = ('role', 'get_resource_name', 'action', 'allowed')
    readonly_fields = ('get_resource_name',)

    def get_resource_name(self, obj):
        return obj.action.resource
    get_resource_name.short_description = "Resource"

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(User, UserAdmin)
admin.site.register(Indicator, IndicatorAdmin)
admin.site.register(ICO, ICOAdmin)
admin.site.register(Case, CaseAdmin)
admin.site.register(CaseHistory, CaseHistoryAdmin)
admin.site.register(AttachedFile, AttachedFileAdmin)
admin.site.register(UppwardRewardInfo, UppwardRewardInfoAdmin)
admin.site.register(CaseInvalidateCandidates, CaseInvalidateCandidatesAdmin)
admin.site.register(Key, KeyAdmin)
admin.site.register(EmailSent, EmailSentAdmin)
admin.site.register(Action, ActionAdmin)
admin.site.register(Role)
admin.site.register(RewardSetting)
admin.site.register(ExchangeToken, ExchangeAdmin)
admin.site.register(RolePermission, RolePermissionAdmin)
admin.site.register(RoleUsageLimit)
