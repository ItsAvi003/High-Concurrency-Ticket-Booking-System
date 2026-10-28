#!/usr/bin/env python
import os
import sys


def main():
    # Local commands default to dev settings; DJANGO_SETTINGS_MODULE in the environment wins.
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
