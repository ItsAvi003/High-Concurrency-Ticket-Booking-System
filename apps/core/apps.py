from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "apps.core"
    label = "core"

    def ready(self):
        from django.core.signals import request_finished

        from apps.core.logging import reset_request_id

        request_finished.connect(reset_request_id, dispatch_uid="core.reset_request_id")
