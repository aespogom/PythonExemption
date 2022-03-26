#!/usr/bin/env python
# -*- coding: utf-8 -*-

def get_checkbox_value(checkbox_value, default=False):
    if not checkbox_value:
        return default
    if 'on' in checkbox_value.lower():
        return True
    else:
        return False