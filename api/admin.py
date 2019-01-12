from django.contrib import admin
from django.contrib.admin.filters import ChoicesFieldListFilter
from django.utils.encoding import force_text
from django.utils.translation import ugettext_lazy as _
from django.contrib.auth.hashers import (check_password, make_password)
import django.forms as forms
# import ModelForm, PasswordInput

from .models import (
    Indicator, ICO, Case, CaseHistory,
    AttachedFile, User, UserStatus,
    UppwardRewardInfo, CaseInvalidateCandidates,
    Key, EmailSent
)
from .email import Email
from .settings import api_settings
from .constants import Constants


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
        except Exception as e:
            pass
        if commit:
            m.save()
        return m


class UserAdmin(admin.ModelAdmin):
    form = UserForm

    list_display = ('id', 'uid', 'email', 'nickname', 'permission')
    list_display_links = ('id', 'uid')
    list_filter = [('permission', EnumFieldListFilter), ('status', EnumFieldListFilter), ]
    search_fields = ('id', 'email', 'nickname')
    fields = ('id', 'uid', 'password', 'confirm_password', 'email', 'nickname', 'created', 'permission', 'status', 'email_notification')
    readonly_fields = ('id', 'uid', 'created')


class IndicatorAdmin(admin.ModelAdmin):
    list_display = ('id', 'uid', 'security_category', 'pattern_type', 'pattern_subtype', 'short_pattern', 'case_id')
    list_display_links = ('id', 'uid')
    list_filter = [('pattern_type', EnumFieldListFilter), ('security_category', EnumFieldListFilter)]
    search_fields = ('id', 'pattern')
    fields = ('id', 'uid', 'case', 'security_category', 'security_tags', 'pattern', 'pattern_type', 'pattern_subtype', 'detail', 'annotation', 'vector', 'environment')
    raw_id_fields = ('case',)
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
        IndicatorInline,
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
