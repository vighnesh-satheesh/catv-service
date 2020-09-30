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

from .models import (
    Indicator, ICO, Case, CaseHistory,
    AttachedFile, User, UserStatus,
    UppwardRewardInfo, CaseInvalidateCandidates,
    Key, EmailSent, Action, Role, RolePermission, RoleUsageLimit, RoleInfo,
    RewardSetting, OrganizationUser, OrganizationInvites,
    OrganizationInviteStatus, OrganizationUserStatus, Usage,
    Organization
)
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
                    api_key_object.expire_datetime = timezone.now() + relativedelta(years=+99)
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
                    usage_role_object.api_calls_left_y = user_role.api_limit_y - user_role.api_limit
                    usage_role_object.catv_calls_left_y = user_role.catv_limit_y - user_role.catv_limit
                    usage_role_object.cara_calls_left_y = user_role.cara_limit_y - user_role.cara_limit
                    usage_role_object.last_renewal_at = timezone.now()
                    usage_role_object.last_renewal_at_y = timezone.now()
                    usage_role_object.save()

                org_invites = OrganizationInvites.objects.select_related('organization').\
                    get(email__iexact=user.email, status=OrganizationInviteStatus.PENDING_APPROVAL.value)
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
    search_fields = ('email',)
    ordering = ('-created',)


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

class RoleUsageInfoAdmin(admin.ModelAdmin):
    list_display = ('role',)

class OrganizationUserAdminInline(admin.TabularInline):
    model = OrganizationUser
    autocomplete_fields = ('user',)

class OrganizationAdmin(admin.ModelAdmin):
    inlines = (OrganizationUserAdminInline,)
    autocomplete_fields = ('administrator',)

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
admin.site.register(RolePermission, RolePermissionAdmin)
admin.site.register(RoleUsageLimit)
admin.site.register(RoleInfo, RoleUsageInfoAdmin)
admin.site.register(Organization, OrganizationAdmin)
admin.site.register(OrganizationUser)
admin.site.register(OrganizationInvites)
